"""Foundation Medicine: mirror report XMLs from the FMI host, load into schema `fmi`.

Covers what seandavi/foundation-medicine-xml-parser extracted (short variants,
CNA, rearrangements, biomarkers, PMI) plus the blocks it skipped: curated
alterations with therapies/trials, VUS flags, pertinent negatives, samples,
QC, non-human reads, amendments. Files that fail land in fmi.load_error
instead of being dropped silently. A ReportId delivered in several files loads one, chosen by
content (fmi.duplicate_file lists the others). Idempotent full rebuild (~30 s).
"""
import glob
import itertools
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

from .config import FMI_SRC, PHI_DB, PHI_DB_KEY, RAW, connect, sql
from .db import bulk_insert

RAW_FMI = f"{RAW}/fmi"
NS = "{http://foundationmedicine.com/compbio/variant-report-external}"


def sync():
    # ponytail: full tar copy every run (rsync isn't on the FMI host); ~450 MB, fine daily
    host, path = FMI_SRC.split(":", 1)
    os.makedirs(RAW_FMI, exist_ok=True)
    # Both exit statuses are checked: in a shell pipeline only the local tar's counted, so an
    # empty or unmounted source looked like success (#75).
    remote = (f'cd {shlex.quote(path)} || exit 1; set -- *.xml; '
              '[ -e "$1" ] || { echo "no *.xml in $PWD" >&2; exit 1; }; exec tar cf - -- "$@"')
    ssh = subprocess.Popen(["ssh", "-o", "BatchMode=yes", host, remote], stdout=subprocess.PIPE)
    untar = subprocess.Popen(["tar", "xf", "-", "-C", RAW_FMI], stdin=ssh.stdout)
    ssh.stdout.close()  # so ssh gets SIGPIPE if the local tar dies first
    untar_rc, ssh_rc = untar.wait(), ssh.wait()
    if ssh_rc or untar_rc:
        sys.exit(f"fmi sync failed: ssh/remote exit {ssh_rc}, local tar exit {untar_rc}")


DDL = """
CREATE TABLE report (
  report_id VARCHAR PRIMARY KEY, sample_name VARCHAR, version INT, test_type VARCHAR, spec_format VARCHAR,
  received_on DATE, collected_on DATE, mrn VARCHAR, dob DATE, gender VARCHAR,
  first_name VARCHAR, last_name VARCHAR, full_name VARCHAR, submitted_diagnosis VARCHAR,
  ordering_md VARCHAR, ordering_md_id VARCHAR, pathologist VARCHAR, medical_facility_name VARCHAR,
  medical_facility_id VARCHAR, specimen_site VARCHAR, country_of_origin VARCHAR,
  disease VARCHAR, disease_ontology VARCHAR, pathology_diagnosis VARCHAR, tissue_of_origin VARCHAR,
  purity_estimate DOUBLE, percent_tumor_nuclei DOUBLE, pipeline_version VARCHAR, study VARCHAR,
  test_request VARCHAR, qc_status VARCHAR, alteration_count INT, sensitizing_count INT, resistive_count INT,
  clinical_trial_count INT, n_amendments INT, pathologist_comment VARCHAR, source_file VARCHAR, mrn_source VARCHAR);
CREATE TABLE sample (report_id VARCHAR, sample_name VARCHAR, bait_set VARCHAR, nucleic_acid_type VARCHAR, mean_exon_depth DOUBLE);
CREATE TABLE short_variant (
  report_id VARCHAR, gene VARCHAR, cds_effect VARCHAR, protein_effect VARCHAR, position VARCHAR, transcript VARCHAR,
  strand VARCHAR, allele_fraction DOUBLE, depth INT, percent_reads DOUBLE, status VARCHAR, functional_effect VARCHAR,
  equivocal BOOLEAN, subclonal BOOLEAN, is_vus BOOLEAN, source VARCHAR);
CREATE TABLE cna (
  report_id VARCHAR, gene VARCHAR, type VARCHAR, copy_number DOUBLE, ratio DOUBLE, number_of_exons VARCHAR,
  position VARCHAR, status VARCHAR, equivocal BOOLEAN, source VARCHAR);
CREATE TABLE rearrangement (
  report_id VARCHAR, targeted_gene VARCHAR, other_gene VARCHAR, description VARCHAR, type VARCHAR, pos1 VARCHAR,
  pos2 VARCHAR, status VARCHAR, in_frame VARCHAR, allele_fraction DOUBLE, percent_reads DOUBLE,
  supporting_read_pairs INT, equivocal BOOLEAN);
CREATE TABLE biomarker (report_id VARCHAR, name VARCHAR, status VARCHAR, score DOUBLE, unit VARCHAR);
CREATE TABLE non_human (report_id VARCHAR, organism VARCHAR, reads_per_million DOUBLE, status VARCHAR);
CREATE TABLE pertinent_negative (report_id VARCHAR, gene VARCHAR);
CREATE TABLE alteration (
  report_id VARCHAR, gene VARCHAR, name VARCHAR, include BOOLEAN, is_equivocal BOOLEAN, is_subclonal BOOLEAN,
  interpretation VARCHAR, clinical_trial_note VARCHAR);
CREATE TABLE therapy (
  report_id VARCHAR, gene VARCHAR, alteration VARCHAR, name VARCHAR, generic_name VARCHAR, fda_approved BOOLEAN,
  effect VARCHAR, include BOOLEAN, include_in_summary BOOLEAN);
CREATE TABLE trial (
  report_id VARCHAR, gene VARCHAR, alteration VARCHAR, nct_id VARCHAR, title VARCHAR, phase VARCHAR,
  target VARCHAR, locations VARCHAR, include BOOLEAN);
CREATE TABLE amendment (report_id VARCHAR, modified_at TIMESTAMP, type VARCHAR, is_signed BOOLEAN);
CREATE TABLE load_error (file VARCHAR, error VARCHAR);
CREATE TABLE duplicate_file (file VARCHAR, chosen_file VARCHAR, reason VARCHAR);
"""


def txt(e, path):
    n = e.find(path) if e is not None else None
    return n.text.strip() if n is not None and n.text and n.text.strip() else None


def f(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def i(x):
    try:
        return int(float(x)) if x not in (None, "") else None
    except ValueError:
        return None


def b(x):
    return None if x is None else str(x).lower() == "true"


def mrn_digits(x):
    """Digits of an MRN text, else None (absent, empty, or no digits)."""
    return ("".join(ch for ch in x if ch.isdigit()) or None) if x else None


# Genes-block Alteration/Name parts that are short variants or copy-number calls (#76).
SYMBOL = re.compile(r"[A-Z0-9][A-Za-z0-9-]*")              # a gene symbol, not "Tumor Mutation Burden"
PROTEIN = re.compile(r"[A-Z*][0-9]+\S*")                    # R175H, Q61*, P72fs*9, A100_L104del
CDS_PREFIXED = re.compile(r"(?:splice site|promoter) (\S+)")  # splice site 560-1G>C, promoter -124C>T
P16 = re.compile(r"p16INK4a ([A-Z*][0-9]+\S*)(?: and p14ARF \S+)?")
CNA_NAME = re.compile(r"(amplification|loss)(?: exons? [0-9]+(?:-[0-9]+)?)?")
GENE_LOSS = re.compile(r"([A-Z0-9][A-Za-z0-9-]*) loss")      # "CDKN2B loss" under Gene/Name "CDKN2A/B"


def genes_block_short_variant(gene, part):
    """(gene, cds_effect, protein_effect) for one ", "-separated part of a Genes-block
    Alteration/Name that is a short variant, else None. `gene` is Gene/Name ("KMT2C (MLL3)")."""
    gene = gene.split(" (")[0] if gene else None
    if m := P16.fullmatch(part):
        return ("CDKN2A", None, m[1]) if gene in ("CDKN2A", "CDKN2A/B") else None
    if not (gene and SYMBOL.fullmatch(gene)):
        return None
    if m := CDS_PREFIXED.fullmatch(part):
        return gene, m[1], part
    return (gene, None, part) if PROTEIN.fullmatch(part) else None


def genes_block_cna(gene, part):
    """(gene, type), type 'amplification' or 'loss', for a copy-number part of a Genes-block
    Alteration/Name, else None."""
    gene = gene.split(" (")[0] if gene else None
    if m := GENE_LOSS.fullmatch(part):
        return m[1], "loss"
    if gene and SYMBOL.fullmatch(gene) and (m := CNA_NAME.fullmatch(part)):
        return gene, m[1]
    return None


def rows_for(path):
    root = ET.parse(path).getroot()
    fr = root.find(".//FinalReport")
    vr = root.find(f".//{NS}variant-report")
    if fr is None and vr is None:
        raise ValueError("neither FinalReport nor variant-report")
    rid = txt(fr, "ReportId") or os.path.basename(path).removesuffix(".xml")
    pmi = fr.find("PMI") if fr is not None else None
    smp = fr.find("Sample") if fr is not None else None
    summ = fr.find("Summaries") if fr is not None else None
    a = (lambda k: vr.get(k)) if vr is not None else (lambda k: None)
    qc = vr.find(f"{NS}quality-control") if vr is not None else None
    amend = fr.findall(".//Amendmends/Amendmend") if fr is not None else []
    # PMI MRN, else ResultsReport/CustomerInformation/MRN: Monitor files have no PMI but carry it
    # there (namespaced rr: in real files, hence {*}), and some reports leave the PMI copy empty (#89).
    # CustomerInformation has no name/DOB/dates.
    pmi_mrn, ci_mrn = mrn_digits(txt(pmi, "MRN")), mrn_digits(txt(root.find("{*}CustomerInformation"), "{*}MRN"))
    mrn, mrn_source = (pmi_mrn, "pmi") if pmi_mrn else (ci_mrn, "customer_information" if ci_mrn else None)
    report = (
        rid, txt(fr, "SampleName"), i(txt(fr, "Version")), txt(smp, "TestType") or a("test-type"), txt(smp, "SpecFormat"),
        txt(smp, "ReceivedDate") or txt(pmi, "ReceivedDate"), txt(pmi, "CollDate"), mrn, txt(pmi, "DOB"),
        txt(pmi, "Gender") or a("gender"),
        txt(pmi, "FirstName"), txt(pmi, "LastName"), txt(pmi, "FullName"), txt(pmi, "SubmittedDiagnosis"),
        txt(pmi, "OrderingMD"), txt(pmi, "OrderingMDId"), txt(pmi, "Pathologist"), txt(pmi, "MedFacilName"),
        txt(pmi, "MedFacilID"), txt(pmi, "SpecSite"), txt(pmi, "CountryOfOrigin"),
        a("disease"), a("disease-ontology"), a("pathology-diagnosis"), a("tissue-of-origin"),
        f(a("purity-assessment")), f(a("percent-tumor-nuclei")), a("pipeline-version"), a("study"),
        a("test-request"), qc.get("status") if qc is not None else None,
        i(summ.get("alterationCount")) if summ is not None else None,
        i(summ.get("sensitizingCount")) if summ is not None else None,
        i(summ.get("resistiveCount")) if summ is not None else None,
        i(summ.get("clinicalTrialCount")) if summ is not None else None,
        len(amend), txt(fr, ".//comments/comment/text"), os.path.relpath(path, RAW),
        mrn_source,
    )
    t = {k: [] for k in ("sample", "short_variant", "cna", "rearrangement", "biomarker", "non_human",
                         "pertinent_negative", "alteration", "therapy", "trial", "amendment")}
    # VariantProperties lists only the VUS calls; absence => not VUS (when a FinalReport exists at all).
    # Raw names plus the parsed (gene, protein_effect) the short_variant rows carry, so an aliased
    # gene ("KMT2C (MLL3)") or a p16INK4a name matches its row on every path (#81).
    vus = None
    if fr is not None:
        vus = set()
        for vp in fr.findall(".//VariantProperties/VariantProperty"):
            if b(vp.get("isVUS")):
                vus.add((vp.get("geneName"), vp.get("variantName")))
                if sv := genes_block_short_variant(vp.get("geneName"), vp.get("variantName") or ""):
                    vus.add((sv[0], sv[2]))
    has_sv = vr is not None and vr.find(f".//{NS}short-variant") is not None
    has_cna = vr is not None and vr.find(f".//{NS}copy-number-alteration") is not None
    if fr is not None:
        for pn in fr.findall(".//PertinentNegatives/PertinentNegative"):
            t["pertinent_negative"].append((rid, txt(pn, "Gene")))
        for g in fr.findall(".//Genes/Gene"):
            gene = txt(g, "Name")
            for al in g.findall("Alterations/Alteration"):
                name = txt(al, "Name")
                props = {p.get("name"): p for p in al.findall("AlterationProperties/AlterationProperty")}
                p0 = props.get(name) or next(iter(props.values()), None)
                t["alteration"].append((rid, gene, name, b(txt(al, "Include")),
                                        b(p0.get("isEquivocal")) if p0 is not None else None,
                                        b(p0.get("isSubclonal")) if p0 is not None else None,
                                        txt(al, "Interpretation"), txt(al, "ClinicalTrialNote")))
                for th in al.findall("Therapies/Therapy"):
                    t["therapy"].append((rid, gene, name, txt(th, "Name"), txt(th, "GenericName"), b(txt(th, "FDAApproved")),
                                         txt(th, "Effect"), b(txt(th, "Include")), b(txt(th, "IncludeInSummary"))))
                # Older reports list their variants only here, with no <short-variant> or
                # <copy-number-alteration> elements: derive rows for those reports only (#76).
                # dnaFraction is a percent; each ", "-joined part has its own AlterationProperty.
                for part in (name or "").split(", "):
                    p = props.get(part)
                    eq = b(p.get("isEquivocal")) if p is not None else None
                    if not has_sv and (sv := genes_block_short_variant(gene, part)):
                        sg, cds, prot = sv
                        af = f(p.get("dnaFraction")) if p is not None else None
                        t["short_variant"].append((rid, sg, cds, prot, None, None, None,
                                                   None if af is None else af / 100, None, None, None, None,
                                                   eq, b(p.get("isSubclonal")) if p is not None else None,
                                                   (sg, prot) in vus or (sg, cds) in vus, "genes_block"))
                    elif not has_cna and (cn := genes_block_cna(gene, part)):
                        t["cna"].append((rid, *cn, None, None, None, None, None, eq, "genes_block"))
        # Older reports list their VUS only in VariantProperties (#79). Same per-report rule as the
        # Genes block; a VariantProperty carries only gene and name, so everything else is NULL.
        if not has_sv:
            derived = {(r[1], r[3]) for r in t["short_variant"]}  # (gene, protein_effect) from the Genes block
            for vp in fr.findall(".//VariantProperties/VariantProperty"):
                sv = genes_block_short_variant(vp.get("geneName"), vp.get("variantName") or "") if b(vp.get("isVUS")) else None
                if sv and (sv[0], sv[2]) not in derived:
                    derived.add((sv[0], sv[2]))
                    t["short_variant"].append((rid, *sv, *[None] * 10, True, "variant_properties"))
        for tr in fr.findall(".//Trials/Trial"):
            t["trial"].append((rid, txt(tr, "Gene"), txt(tr, "Alteration"), txt(tr, "NCTID"), txt(tr, "Title"),
                               txt(tr, "StudyPhase"), txt(tr, "Target"), txt(tr, "Locations"), b(txt(tr, "Include"))))
        for am in amend:
            t["amendment"].append((rid, txt(am, "ModifiedDts"), txt(am, "Type"), b(txt(am, "IsSigned"))))
    if vr is not None:
        for s in vr.findall(f"{NS}samples/{NS}sample"):
            t["sample"].append((rid, s.get("name"), s.get("bait-set"), s.get("nucleic-acid-type"), f(s.get("mean-exon-depth"))))
        for v in vr.findall(f".//{NS}short-variant"):
            g = v.get("gene")
            t["short_variant"].append((rid, g, v.get("cds-effect"), v.get("protein-effect"), v.get("position"),
                                       v.get("transcript"), v.get("strand"), f(v.get("allele-fraction")), i(v.get("depth")),
                                       f(v.get("percent-reads")), v.get("status"), v.get("functional-effect"),
                                       b(v.get("equivocal")), b(v.get("subclonal")),
                                       None if vus is None else ((g, v.get("protein-effect")) in vus or (g, v.get("cds-effect")) in vus),
                                       "variant_report"))
        for c in vr.findall(f".//{NS}copy-number-alteration"):
            t["cna"].append((rid, c.get("gene"), c.get("type"), f(c.get("copy-number")), f(c.get("ratio")),
                             c.get("number-of-exons"), c.get("position"), c.get("status"), b(c.get("equivocal")),
                             "variant_report"))
        for r in vr.findall(f".//{NS}rearrangement"):
            t["rearrangement"].append((rid, r.get("targeted-gene"), r.get("other-gene"), r.get("description"), r.get("type"),
                                       r.get("pos1"), r.get("pos2"), r.get("status"), r.get("in-frame"),
                                       f(r.get("allele-fraction")), f(r.get("percent-reads")),
                                       i(r.get("supporting-read-pairs")), b(r.get("equivocal"))))
        bm = vr.find(f"{NS}biomarkers")
        for x in (bm if bm is not None else []):
            t["biomarker"].append((rid, x.tag.split("}")[-1], x.get("status"), f(x.get("score")), x.get("unit")))
        for x in vr.findall(f".//{NS}non-human"):
            t["non_human"].append((rid, x.get("organism"), f(x.get("reads-per-million")), x.get("status")))
    return report, t


# Rank of a file among files sharing a ReportId (#81), compared in this order; the max is loaded.
CHOICE = ("variant_elements", "version", "amendments", "mtime", "path")


def choice_key(path, report, t):
    """CHOICE tuple for one parsed file: has variant-report short variants, CNAs or rearrangements;
    FinalReport Version (-1 if absent); amendment count; file mtime; path relative to RAW."""
    return (bool(t["rearrangement"]) or any(r[-1] == "variant_report" for r in t["short_variant"] + t["cna"]),
            -1 if report[2] is None else report[2], report[35], os.path.getmtime(path), os.path.relpath(path, RAW))


def patient_identity(report):
    """deid.IDENTITY for one fmi.report row: MRN digits (PMI, else CustomerInformation), else
    lower(last)|lower(first)|dob, else None."""
    mrn, dob, first, last = report[7], report[8], report[10], report[11]
    if mrn:
        return mrn
    return None if None in (last, first, dob) else f"{last.lower()}|{first.lower()}|{dob}"


def same_patient(a, b):
    """Two fmi.report rows of one ReportId are one patient. When both carry an MRN it decides, as in
    deid.IDENTITY, so a corrected name or DOB in a re-delivery is not a conflict. Otherwise they are
    one patient when both carry lower last|first|dob and it agrees, or when neither carries any
    identity (as before #89). A copy may hold the MRN only in CustomerInformation while its twin has
    only name and DOB (#89), so identities can differ in kind. Not transitive: callers must check
    every pair."""
    if a[7] and b[7]:
        return a[7] == b[7]
    na, nb = (None if None in (r[11], r[10], r[8]) else (r[11].lower(), r[10].lower(), r[8]) for r in (a, b))
    if na and nb:
        return na == nb
    return patient_identity(a) is None and patient_identity(b) is None


def load():
    files = sorted(glob.glob(f"{RAW_FMI}/*.xml"))
    if not files:
        sys.exit(f"no XML under {RAW_FMI} — run `genomics sync --vendor fmi` first")
    con = connect(phi=(PHI_DB, PHI_DB_KEY))
    con.execute("CREATE SCHEMA IF NOT EXISTS fmi; USE phi.fmi")
    for tname in ("report", "sample", "short_variant", "cna", "rearrangement", "biomarker", "non_human",
                  "pertinent_negative", "alteration", "therapy", "trial", "amendment", "load_error", "duplicate_file"):
        con.execute(f"DROP TABLE IF EXISTS {tname}")
    con.execute(DDL)
    parsed, errors = {}, []
    for path in files:
        try:
            report, t = rows_for(path)
        except Exception as e:  # noqa: BLE001 — logged to a table, never swallowed
            errors.append((os.path.relpath(path, RAW), f"{type(e).__name__}: {e}"[:300]))
            continue
        parsed.setdefault(report[0], []).append((path, report, t))
    reports, children, duplicates = [], {}, []
    for rid, cands in parsed.items():
        # Files of one ReportId must be one patient; otherwise load none (#81)
        if not all(same_patient(x[1], y[1]) for x, y in itertools.combinations(cands, 2)):
            errors += [(os.path.relpath(c[0], RAW), f"ValueError: conflicting patient identity for report_id {rid}")
                       for c in cands]
            continue
        # FMI re-delivered some reports as a reduced copy without the variant report; the
        # filename order picked that copy (#81). Choose by content; log the others.
        keys = [choice_key(*c) for c in cands]
        best = max(range(len(cands)), key=keys.__getitem__)
        path, report, t = cands[best]
        if report[7] is None:  # chosen copy has no MRN anywhere: take it from a matching copy (#89)
            donor = next((c[1] for c in cands if c[1][7]), None)
            if donor:
                report = report[:7] + (donor[7],) + report[8:-1] + ("duplicate_copy",)
        reports.append(report)
        for k, rows in t.items():
            children.setdefault(k, []).extend(rows)
        for j, c in enumerate(cands):
            if j != best:
                reason = next(n for n, a, b_ in zip(CHOICE, keys[best], keys[j]) if a != b_)
                duplicates.append((os.path.relpath(c[0], RAW), os.path.relpath(path, RAW), reason))
    bulk_insert(con, "report", reports)
    for k, rows in children.items():
        bulk_insert(con, k, rows)
    bulk_insert(con, "load_error", errors)
    bulk_insert(con, "duplicate_file", duplicates)
    con.execute(sql("fmi_views.sql"))
    for tname in ("report", "short_variant", "cna", "rearrangement", "biomarker", "alteration", "therapy",
                  "pertinent_negative", "load_error", "duplicate_file"):
        print(f"fmi.{tname:18s} {con.execute(f'SELECT count(*) FROM {tname}').fetchone()[0]:>10,}")
    con.close()
