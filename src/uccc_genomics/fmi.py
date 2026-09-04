"""Foundation Medicine: mirror report XMLs from dccapp720, load into schema `fmi`.

Covers what seandavi/foundation-medicine-xml-parser extracted (short variants,
CNA, rearrangements, biomarkers, PMI) plus the blocks it skipped: curated
alterations with therapies/trials, VUS flags, pertinent negatives, samples,
QC, non-human reads, amendments. Files that fail land in fmi.load_error
instead of being dropped silently. Idempotent full rebuild (~30 s).
"""
import glob
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from .config import FMI_SRC, PHI_DB, PHI_DB_KEY, RAW, connect, sql
from .db import bulk_insert

RAW_FMI = f"{RAW}/fmi"
NS = "{http://foundationmedicine.com/compbio/variant-report-external}"


def sync():
    # ponytail: full tar copy every run (rsync isn't on dccapp720); ~450 MB, fine daily
    host, path = FMI_SRC.split(":", 1)
    os.makedirs(RAW_FMI, exist_ok=True)
    subprocess.run(f"ssh -o BatchMode=yes {host} 'cd {path} && tar cf - *.xml' | tar xf - -C {RAW_FMI}",
                   shell=True, check=True)


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
  clinical_trial_count INT, n_amendments INT, pathologist_comment VARCHAR, source_file VARCHAR);
CREATE TABLE sample (report_id VARCHAR, sample_name VARCHAR, bait_set VARCHAR, nucleic_acid_type VARCHAR, mean_exon_depth DOUBLE);
CREATE TABLE short_variant (
  report_id VARCHAR, gene VARCHAR, cds_effect VARCHAR, protein_effect VARCHAR, position VARCHAR, transcript VARCHAR,
  strand VARCHAR, allele_fraction DOUBLE, depth INT, percent_reads DOUBLE, status VARCHAR, functional_effect VARCHAR,
  equivocal BOOLEAN, subclonal BOOLEAN, is_vus BOOLEAN);
CREATE TABLE cna (
  report_id VARCHAR, gene VARCHAR, type VARCHAR, copy_number DOUBLE, ratio DOUBLE, number_of_exons VARCHAR,
  position VARCHAR, status VARCHAR, equivocal BOOLEAN);
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
    mrn = txt(pmi, "MRN")
    mrn = "".join(ch for ch in mrn if ch.isdigit()) if mrn else None
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
    )
    t = {k: [] for k in ("sample", "short_variant", "cna", "rearrangement", "biomarker", "non_human",
                         "pertinent_negative", "alteration", "therapy", "trial", "amendment")}
    # VariantProperties lists only the VUS calls; absence => not VUS (when a FinalReport exists at all)
    vus = {(vp.get("geneName"), vp.get("variantName")) for vp in fr.findall(".//VariantProperties/VariantProperty")
           if b(vp.get("isVUS"))} if fr is not None else None
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
                                       None if vus is None else ((g, v.get("protein-effect")) in vus or (g, v.get("cds-effect")) in vus)))
        for c in vr.findall(f".//{NS}copy-number-alteration"):
            t["cna"].append((rid, c.get("gene"), c.get("type"), f(c.get("copy-number")), f(c.get("ratio")),
                             c.get("number-of-exons"), c.get("position"), c.get("status"), b(c.get("equivocal"))))
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


def load():
    files = sorted(glob.glob(f"{RAW_FMI}/*.xml"))
    if not files:
        sys.exit(f"no XML under {RAW_FMI} — run `genomics sync --vendor fmi` first")
    con = connect(phi=(PHI_DB, PHI_DB_KEY))
    con.execute("CREATE SCHEMA IF NOT EXISTS fmi; USE phi.fmi")
    for tname in ("report", "sample", "short_variant", "cna", "rearrangement", "biomarker", "non_human",
                  "pertinent_negative", "alteration", "therapy", "trial", "amendment", "load_error"):
        con.execute(f"DROP TABLE IF EXISTS {tname}")
    con.execute(DDL)
    reports, seen, errors = [], set(), []
    children = {}
    for path in files:
        try:
            report, t = rows_for(path)
            if report[0] in seen:
                raise ValueError(f"duplicate report_id {report[0]}")
            seen.add(report[0])
            reports.append(report)
            for k, rows in t.items():
                children.setdefault(k, []).extend(rows)
        except Exception as e:  # noqa: BLE001 — logged to a table, never swallowed
            errors.append((os.path.relpath(path, RAW), f"{type(e).__name__}: {e}"[:300]))
    bulk_insert(con, "report", reports)
    for k, rows in children.items():
        bulk_insert(con, k, rows)
    bulk_insert(con, "load_error", errors)
    con.execute(sql("fmi_views.sql"))
    for tname in ("report", "short_variant", "cna", "rearrangement", "biomarker", "alteration", "therapy",
                  "pertinent_negative", "load_error"):
        print(f"fmi.{tname:18s} {con.execute(f'SELECT count(*) FROM {tname}').fetchone()[0]:>10,}")
    con.close()
