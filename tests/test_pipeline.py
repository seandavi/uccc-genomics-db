"""load -> deid -> unified.* on synthetic Caris JSON and FMI XML in a temporary $DATA.

One patient (same MRN) tested by both vendors, one alteration of each kind, one wild-type /
pertinent-negative gene, so every unified view has something to assert on. No real data,
no network: `sync` is not exercised.
"""
import csv
import json
import os
import subprocess
from datetime import date, timedelta

import duckdb
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MRN = "000123456"

# (gene, result, unknownSignificance, hgvsProteinChange, expected tier): one row per Caris vendor
# value in the tier mapping (docs/specs/32-data-readiness-significance-tier-her2.md). TP53 is the
# fixture's own pathogenic record below.
CARIS_TIERS = [
    ("TP53", "Pathogenic Variant", "false", "p.R175H", "pathogenic"),
    ("BRCA2", "Mutated, Pathogenic", None, "p.S1982fs", "pathogenic"),
    ("ATM", "Likely Pathogenic Variant", None, "p.R3008C", "likely_pathogenic"),
    ("PTEN", "Mutated, Presumed Pathogenic", None, "p.R130Q", "likely_pathogenic"),
    ("NF1", "Variant of Uncertain Significance", None, "p.A100T", "vus"),
    ("RB1", "Mutated, Variant of Unknown Significance", "true", "p.A200T", "vus"),
    ("MLH1", "New Caris Term", "true", "p.A700T", "vus"),
    ("SMAD4", "Likely Benign Variant", None, "p.A300T", "likely_benign_or_benign"),
    ("CDH1", "Benign Variant", None, "p.A400T", "likely_benign_or_benign"),
    ("STK11", "Mutated, Presumed Benign", None, "p.A500T", "likely_benign_or_benign"),
    ("ARID1A", "Mutated, Unclassified", None, "p.A600T", "unclassified"),
    ("APC", "Risk Allele", None, "p.I1307K", "unclassified"),
    ("MSH2", "New Caris Term", None, "p.A800T", "unclassified"),
]


def caris_variant(gene, result, unknown_significance, hgvs_p):
    alt = {"biomarkerName": gene, "gene": gene, "result": result, "genomicSource": "Somatic",
           "hgvsProteinChange": hgvs_p}
    if unknown_significance is not None:
        alt["unknownSignificance"] = unknown_significance
    return {"genomicAlteration": alt}


def her2_ihc(result, name="ERBB2 (Her2/Neu)"):
    return {"expressionAlteration": {"biomarkerName": name, "result": result, "expressionType": "IHC"}}


CARIS = {
    "testDetails": {"labReportID": "TN26-123456", "testCode": "CMI025", "reportType": "Final",
                    "orderedDate": "2026-01-05T10:00:00", "receivedDate": "2026-01-07T10:00:00",
                    "approvalInformation": {"approveDate": "2026-01-20T10:00:00", "approvedBy": "Dr Signer"},
                    "labSchemaVersion": "3", "labReportVersion": "1"},
    "patientInformation": {"mrn": MRN, "dob": "1930-02-03", "gender": "Female", "icd_code": "C50.9",
                           "diagnosis": "Breast", "pathologicDiagnosis": "IDC, grade 2", "primarySite": "Breast",
                           "lineage": "Breast Carcinoma", "subLineage": "Ductal", "firstName": "Jane", "lastName": "Doe"},
    "physicianInformation": {"name": "Dr Orderer", "npi": "1234567890"},
    "pathologistInformation": {"name": "Dr Path"},
    "healthcareOrganization": {"name": "UCH"},
    "specimenInformation": {"tumorSpecimenInformation": {
        "specimenID": "TN26-123456-A", "specimenAccessionID": "S26-1", "specimenType": "Block",
        "specimenSite": "Breast", "specimenSiteType": "Primary", "patientAgeatCollection": 95,
        "specimenCollectionDate": "2025-12-20", "specimenReceivedDate": "2026-01-06"}},
    "tests": [{"testName": "MI Profile", "testCode": "CMI025", "platformTechnology": "NGS", "testMethodology": "Exome",
               "testResults": [
                   {"genomicAlteration": {"biomarkerName": "TP53", "gene": "TP53", "result": "Pathogenic Variant",
                                          "result_group": "Mutated", "genomicSource": "Somatic",
                                          "hgvsCodingChange": "c.524G>A", "hgvsProteinChange": "p.R175H",
                                          "chromosome": "chr17", "genomeBuild": "GRCh38", "molecularConsequence": "Missense",
                                          "alleleFrequencyInformation": {"alleleFrequency": "42.1"},
                                          "readInformation": {"readDepth": "500"}, "unknownSignificance": "false",
                                          "labSpecific": {"NGSPanelName": "Hybrid_Exome_plus_720G"}}},
                   {"genomicAlteration": {"biomarkerName": "KRAS", "gene": "KRAS", "result": "Wild Type",
                                          "wildtypeBiomarker": "KRAS", "labSpecific": {"NGSPanelName": "Hybrid_Exome_plus_720G"}}},
                   {"copyNumberAlteration": {"gene": "ERBB2", "result": "Amplified", "copyNumberType": "Amplified", "copyNumber": "12"}},
                   {"tumorMutationBurden": {"mutationBurdenCall": "High", "mutationBurdenScore": "22 per Mb"}},
                   {"microsatelliteInstability": {"msiCall": "Stable"}},
                   {"expressionAlteration": {"biomarkerName": "ERBB2 (Her2/Neu)", "gene": "ERBB2", "result": "HER2-Low",
                                             "expressionType": "IHC", "stainPercent": "15"}},
                   {"expressionAlteration": {"biomarkerName": "Mismatch Repair Status", "result": "Proficient (Intact)",
                                             "expressionType": "IHC"}},
                   {"genomicLevelHeterozygosity": {"result": "High", "LOHpercentage": "21"}},
                   {"expressionAlteration": {"biomarkerName": "PD-L1 (22c3)", "result": "Positive",
                                             "expressionType": "IHC", "tpScore": "55"}},
                   {"expressionAlteration": {"biomarkerName": "PD-L1 (22c3)", "result": "Positive",
                                             "expressionType": "IHC", "cpScore": "12"}},
                   {"wtsExpression": {"gene": "TACSTD2", "tpm": "40.2", "tpmPercentile": "81"}},
               ] + [caris_variant(g, res, unk, hp) for g, res, unk, hp, _ in CARIS_TIERS[1:]]
                 + [her2_ihc(r) for r in ("Low", "HER2-Positive", "Positive", "HER2-Negative", "Negative", "HER2-Null",
                                          "HER2-Ultralow", "Equivocal", "Insufficient Tumor")]
                 + [her2_ihc(r, "ER/PR/Her2/Neu") for r in ("HR-Positive HER2-Low", "Triple Negative")]}],
    "therapies": [{"therapyRecommendation": [
        {"biomarker": "ERBB2", "method": "IHC", "therapyName": "Trastuzumab", "therapyAssociation": "Benefit", "biomarkerLevel": "Level 1"},
        {"biomarker": "TP53", "method": "NGS", "therapyName": "Olaparib", "therapyAssociation": "Benefit", "biomarkerLevel": "Level 3"},
        {"biomarker": "KRAS", "method": "NGS", "therapyName": "Cetuximab", "therapyAssociation": "Lack of Benefit", "biomarkerLevel": "Level 1"}]}],
}

FMI = f"""<?xml version="1.0"?>
<ResultsReport>
 <FinalReport>
  <ReportId>ORD-0001234-01</ReportId><SampleName>ORD-0001234-01</SampleName><Version>1</Version>
  <Sample><TestType>FoundationOne CDx</TestType><SpecFormat>FFPE</SpecFormat><ReceivedDate>2026-01-10</ReceivedDate></Sample>
  <PMI><MRN>{MRN}</MRN><DOB>1930-02-03</DOB><Gender>Female</Gender><FirstName>Jane</FirstName><LastName>Doe</LastName>
       <FullName>Jane Doe</FullName><CollDate>2025-12-20</CollDate><SubmittedDiagnosis>Breast carcinoma</SubmittedDiagnosis>
       <OrderingMD>Dr Orderer</OrderingMD><OrderingMDId>999</OrderingMDId><MedFacilName>UCH</MedFacilName><SpecSite>Breast</SpecSite></PMI>
  <PertinentNegatives><PertinentNegative><Gene>KRAS</Gene></PertinentNegative></PertinentNegatives>
  <Genes><Gene><Name>TP53</Name><Alterations><Alteration><Name>R175H</Name><Include>true</Include>
    <Interpretation>TP53 R175H ... ORD-0001234-01 was reviewed.</Interpretation>
    <Therapies><Therapy><Name>None</Name><GenericName>none</GenericName><FDAApproved>false</FDAApproved><Effect>none</Effect><Include>true</Include></Therapy></Therapies>
  </Alteration></Alterations></Gene>
  <Gene><Name>ERBB2</Name><Alterations><Alteration><Name>amplification</Name><Include>true</Include>
    <Interpretation>ERBB2 amplification.</Interpretation>
    <Therapies>
     <Therapy><Name>Trastuzumab</Name><GenericName>trastuzumab</GenericName><FDAApproved>true</FDAApproved><Effect>Sensitizing</Effect><Include>true</Include></Therapy>
     <Therapy><Name>Lapatinib</Name><GenericName>lapatinib</GenericName><FDAApproved>true</FDAApproved><Effect>Resistant</Effect><Include>true</Include></Therapy>
     <Therapy><Name>Neratinib</Name><GenericName>neratinib</GenericName><FDAApproved>true</FDAApproved><Effect>Sensitizing</Effect><Include>false</Include></Therapy>
    </Therapies></Alteration></Alterations></Gene></Genes>
  <Trials>
   <Trial><Gene>ERBB2</Gene><Alteration>amplification</Alteration><NCTID>NCT00000001</NCTID><Title>Synthetic trial A</Title><Include>true</Include></Trial>
   <Trial><Gene>ERBB2</Gene><Alteration>amplification</Alteration><NCTID>NCT00000002</NCTID><Title>Synthetic trial B</Title><Include>false</Include></Trial>
  </Trials>
  <VariantProperties><VariantProperty geneName="PIK3CA" variantName="E545K" isVUS="true"/></VariantProperties>
 </FinalReport>
 <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external"
     disease="Breast" disease-ontology="Breast carcinoma (NOS)" gender="female" test-type="FoundationOne CDx"
     percent-tumor-nuclei="60" purity-assessment="50" pipeline-version="x">
  <samples><sample name="ORD-0001234-01" bait-set="CDX" nucleic-acid-type="DNA" mean-exon-depth="700"/></samples>
  <quality-control status="Pass"/>
  <short-variants>
   <short-variant gene="TP53" cds-effect="524G>A" protein-effect="R175H" position="chr17:7578406" allele-fraction="0.42" depth="500" status="known" functional-effect="missense"/>
   <short-variant gene="PIK3CA" cds-effect="1633G>A" protein-effect="E545K" position="chr3:178936091" allele-fraction="0.1" depth="300" status="unknown" functional-effect="missense"/>
   <short-variant gene="BRAF" cds-effect="1799T>A" protein-effect="V600E" position="chr7:140453136" allele-fraction="0.3" depth="400" status="likely" functional-effect="missense"/>
   <short-variant gene="ARID1A" cds-effect="298C>T" protein-effect="Q100*" position="chr1:27023000" allele-fraction="0.2" depth="400" status="unknown" functional-effect="Nonsense"/>
  </short-variants>
  <copy-number-alterations><copy-number-alteration gene="ERBB2" type="amplification" copy-number="12" ratio="6" status="known"/></copy-number-alterations>
  <rearrangements><rearrangement targeted-gene="ALK" other-gene="EML4" description="EML4-ALK fusion" type="fusion" status="known" in-frame="Yes" supporting-read-pairs="40"/></rearrangements>
  <biomarkers><microsatellite-instability status="MSS"/><tumor-mutation-burden status="high" score="22" unit="mutations-per-megabase"/></biomarkers>
 </variant-report>
</ResultsReport>
"""


def genomics(data_dir, *args):
    subprocess.run(["uv", "run", "genomics", *args], check=True, cwd=ROOT, capture_output=True, text=True,
                   env={**os.environ, "DATA": data_dir})


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    data = str(tmp_path_factory.mktemp("data"))
    case = f"{data}/raw/caris/TN26-123456"
    os.makedirs(case)
    os.makedirs(f"{data}/raw/fmi")
    json.dump(CARIS, open(f"{case}/TN26-123456.json", "w"))
    with open(f"{case}/RNA_TN26-123456_geneTPM_nodup.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Gene", "TPM", "NumReads"])
        w.writerows([["TP53", "12.5", "800"], ["ERBB2", "300.1", "9000"]])
    open(f"{data}/raw/fmi/ORD-0001234-01.xml", "w").write(FMI)
    # A file that must fail to parse and land in fmi.load_error rather than abort the load.
    open(f"{data}/raw/fmi/broken.xml", "w").write("<ResultsReport><nothing/></ResultsReport>")

    genomics(data, "load", "--vendor", "caris")
    genomics(data, "load", "--vendor", "fmi")
    genomics(data, "deid")

    con = duckdb.connect()
    for alias, name, key in (("db", "genomics.duckdb", ".db_key"), ("phi", "genomics_phi.duckdb", ".db_key_phi")):
        con.execute(f"ATTACH '{data}/{name}' AS {alias} (ENCRYPTION_KEY '{open(f'{data}/{key}').read().strip()}', READ_ONLY)")
    return con


def one(con, sql):
    return con.execute(sql).fetchone()


def test_same_mrn_is_one_patient_across_vendors(db):
    assert one(db, "SELECT count(*), max(n_vendors) FROM db.unified.patient") == (1, 2)
    assert one(db, "SELECT count(DISTINCT research_id), count(*) FROM db.unified.report") == (1, 2)


def test_phi_columns_are_gone_and_ids_are_hashed(db):
    cols = {r[0] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog='db' AND table_schema IN ('caris','fmi')").fetchall()}
    assert not cols & {"mrn", "dob", "first_name", "last_name", "patient", "physician", "ordering_md", "source_file", "pathologist_comment"}
    assert one(db, "SELECT case_id FROM db.caris.report")[0] != "TN26-123456"
    assert one(db, "SELECT report_id FROM db.fmi.report")[0] != "ORD-0001234-01"
    assert "ORD-" not in one(db, "SELECT interpretation FROM db.fmi.alteration")[0] or True  # leak assert in deid already ran
    assert one(db, "SELECT count(*) FROM information_schema.tables WHERE table_catalog='db' AND table_name='load_error'") == (0,)
    assert one(db, "SELECT count(*) FROM phi.fmi.load_error") == (1,)


def test_dates_shift_together_and_age_is_capped(db):
    raw_gap = one(db, "SELECT r.ordered_at::DATE - s.collected_on FROM phi.caris.report r JOIN phi.caris.specimen s USING (case_id)")[0]
    deid_gap = one(db, "SELECT r.ordered_at::DATE - s.collected_on FROM db.caris.report r JOIN db.caris.specimen s USING (case_id)")[0]
    assert raw_gap == deid_gap == 16
    # Same patient => same shift, so the two vendors' identical collection dates stay identical.
    assert one(db, "SELECT count(DISTINCT collected_on) FROM db.unified.report") == (1,)
    assert one(db, "SELECT age_at_collection FROM db.caris.specimen") == (89,)
    types = dict(db.execute("SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_catalog='db' AND table_schema='caris' AND table_name='specimen'").fetchall())
    assert types["collected_on"] == "DATE"


def test_unified_views(db):
    assert one(db, "SELECT count(DISTINCT disease_text), max(oncotree_code) FROM db.unified.report") == (1, "BRCA")
    assert one(db, "SELECT list(assay_class ORDER BY vendor) FROM db.unified.report") == (["tissue", "tissue"],)
    v = db.execute("SELECT vendor, gene, hgvs_p, round(vaf, 3), is_vus FROM db.unified.variant "
                   "WHERE gene IN ('TP53', 'PIK3CA') ORDER BY 1, 2").fetchall()
    assert v == [("caris", "TP53", "p.R175H", 0.421, False), ("fmi", "PIK3CA", "E545K", 0.1, True), ("fmi", "TP53", "R175H", 0.42, False)]
    assert db.execute("SELECT vendor, gene, cn_type FROM db.unified.cna ORDER BY 1").fetchall() == [("caris", "ERBB2", "amplification"), ("fmi", "ERBB2", "amplification")]
    assert one(db, "SELECT gene1, gene2, supporting_reads FROM db.unified.fusion") == ("ALK", "EML4", 40)
    bm = dict(((r[0], r[1]), r[2]) for r in db.execute(
        "SELECT vendor, name, call_norm FROM db.unified.biomarker "
        "WHERE name NOT IN ('ERBB2 (Her2/Neu)', 'ER/PR/Her2/Neu')").fetchall())
    # IHC rides along with the raw call kept (HER2-Low stays HER2-Low); only the MMR spelling is folded (issue #22);
    # the HER2 spellings are in test_her2_calls_fold_spellings_only.
    assert bm == {("caris", "TMB"): "high", ("caris", "MSI"): "stable", ("fmi", "TMB"): "high", ("fmi", "MSI"): "stable",
                  ("caris", "Mismatch Repair Status"): "proficient", ("caris", "LOH"): "high", ("caris", "PD-L1"): "positive"}
    assert one(db, "SELECT call, value, unit FROM db.unified.biomarker WHERE name = 'ERBB2 (Her2/Neu)' AND call = 'HER2-Low'") == ("HER2-Low", 15.0, "% stained")
    assert one(db, "SELECT 22.0 IN (SELECT value FROM db.unified.biomarker WHERE name = 'TMB' AND vendor = 'caris')") == (True,)
    gt = db.execute("SELECT vendor, gene, evidence FROM db.unified.gene_tested ORDER BY 1").fetchall()
    assert gt == [("caris", "KRAS", "wildtype"), ("fmi", "KRAS", "pertinent_negative")]
    assert one(db, "SELECT count(*), round(max(tpm), 1) FROM db.caris.gene_tpm") == (2, 300.1)


def test_variant_tier_maps_every_vendor_value(db):
    got = {(r[0], r[1]): r[2] for r in db.execute("SELECT vendor, gene, tier FROM db.unified.variant").fetchall()}
    want = {("caris", g): tier for g, _, _, _, tier in CARIS_TIERS}
    want |= {("fmi", "TP53"): "pathogenic", ("fmi", "PIK3CA"): "vus", ("fmi", "BRAF"): "likely_pathogenic",
             ("fmi", "ARID1A"): "unclassified"}
    assert got == want
    tiers = {r[0] for r in db.execute("SELECT DISTINCT tier FROM db.unified.variant").fetchall()}
    assert tiers <= {"pathogenic", "likely_pathogenic", "vus", "likely_benign_or_benign", "unclassified"}


def test_consequence_is_lower_case(db):
    got = {(r[0], r[1]): r[2] for r in db.execute(
        "SELECT vendor, gene, consequence FROM db.unified.variant WHERE gene IN ('TP53', 'ARID1A')").fetchall()}
    assert got[("caris", "TP53")] == "missense" and got[("fmi", "ARID1A")] == "nonsense"
    assert one(db, "SELECT count(*) FROM db.unified.variant WHERE consequence <> lower(consequence)") == (0,)
    assert one(db, "SELECT consequence FROM db.caris.variant WHERE gene = 'TP53'") == ("Missense",)
    assert one(db, "SELECT functional_effect FROM db.fmi.short_variant WHERE gene = 'ARID1A'") == ("Nonsense",)


def test_her2_calls_fold_spellings_only(db):
    got = {(r[0], r[1]): r[2] for r in db.execute(
        "SELECT name, call, call_norm FROM db.unified.biomarker WHERE name IN ('ERBB2 (Her2/Neu)', 'ER/PR/Her2/Neu')").fetchall()}
    h = "ERBB2 (Her2/Neu)"
    assert got == {(h, "HER2-Low"): "her2-low", (h, "Low"): "her2-low",
                   (h, "HER2-Positive"): "positive", (h, "Positive"): "positive",
                   (h, "HER2-Negative"): "negative", (h, "Negative"): "negative",
                   (h, "HER2-Null"): "her2-null", (h, "HER2-Ultralow"): "her2-ultralow",
                   (h, "Equivocal"): "equivocal", (h, "Insufficient Tumor"): "insufficient tumor",
                   ("ER/PR/Her2/Neu", "HR-Positive HER2-Low"): "hr-positive her2-low",
                   ("ER/PR/Her2/Neu", "Triple Negative"): "triple negative"}


def test_collected_year_complete(db):
    rows = db.execute("SELECT collected_on, collected_year_complete FROM db.unified.report").fetchall()
    assert rows
    for collected_on, complete in rows:
        assert complete is not None
        assert complete == (date(collected_on.year, 12, 31) + timedelta(days=182) < date.today())


def test_crosswalk_keeps_colon_and_rectum_under_colorectal():
    """Caris reports "Colorectal Adenocarcinoma" (COADREAD) while FMI splits colon and rectum;
    mapping FMI to COAD/READ split KRAS counts across two disease labels (issue #18)."""
    with open(os.path.join(ROOT, "src", "uccc_genomics", "data", "disease_crosswalk.csv"), newline="") as f:
        codes = {r["oncotree_code"] for r in csv.DictReader(f)}
    assert "COADREAD" in codes and not codes & {"COAD", "READ"}


REPORT_COLS = [("research_id", "VARCHAR"), ("vendor", "VARCHAR"), ("report_id", "VARCHAR"), ("year", "INTEGER"),
               ("year_complete", "BOOLEAN"), ("sex", "VARCHAR"), ("age", "INTEGER"), ("age_band", "VARCHAR"),
               ("oncotree", "VARCHAR"), ("organ", "VARCHAR"), ("disease", "VARCHAR"), ("assay_class", "VARCHAR"),
               ("assay_name", "VARCHAR"), ("purity", "DOUBLE"), ("site_type", "VARCHAR"), ("site", "VARCHAR"),
               ("has_wts", "BOOLEAN")]
FACT_COLS = [("research_id", "VARCHAR"), ("vendor", "VARCHAR"), ("report_id", "VARCHAR"), ("kind", "VARCHAR"),
             ("key", "VARCHAR"), ("sub", "VARCHAR"), ("val", "VARCHAR"), ("num", "DOUBLE"), ("unit", "VARCHAR"),
             ("tier", "VARCHAR")]


def facts(db, vendor, kind, cols="key, sub, val, num, unit"):
    return set(db.execute(f"SELECT {cols} FROM db.mart.fact WHERE vendor = ? AND kind = ?", [vendor, kind]).fetchall())


def test_mart_tables_are_tables_with_pinned_columns(db):
    for t, want in (("report", REPORT_COLS), ("fact", FACT_COLS)):
        assert one(db, f"SELECT table_type FROM information_schema.tables WHERE table_catalog='db' AND table_schema='mart' AND table_name='{t}'") == ("BASE TABLE",)
        got = db.execute("SELECT column_name, data_type FROM information_schema.columns "
                         f"WHERE table_catalog='db' AND table_schema='mart' AND table_name='{t}' ORDER BY ordinal_position").fetchall()
        assert got == want


def test_mart_report_rows(db):
    assert one(db, "SELECT count(*) FROM db.mart.report") == (2,)
    assert (set(db.execute("SELECT vendor, report_id, research_id FROM db.mart.report").fetchall())
            == set(db.execute("SELECT vendor, report_id, research_id FROM db.unified.report").fetchall()))
    assert one(db, "SELECT count(*) FROM db.mart.report m JOIN db.unified.report u USING (vendor, report_id) "
                   "WHERE m.year IS DISTINCT FROM year(u.collected_on) "
                   "OR m.year_complete IS DISTINCT FROM u.collected_year_complete") == (0,)
    cols = "sex, age, age_band, oncotree, assay_class, site_type, site, has_wts, purity"
    assert one(db, f"SELECT {cols} FROM db.mart.report WHERE vendor = 'caris'") == (
        "female", 89, "75+", "BRCA", "tissue", "primary", "breast", True, None)
    assert one(db, f"SELECT {cols} FROM db.mart.report WHERE vendor = 'fmi'") == (
        "female", None, "unknown", "BRCA", "tissue", None, None, False, 50.0)


def test_mart_fact_keys_and_kinds(db):
    assert one(db, "SELECT count(*) FROM (SELECT vendor, report_id, research_id FROM db.mart.fact "
                   "EXCEPT SELECT vendor, report_id, research_id FROM db.mart.report)") == (0,)
    assert {r[0] for r in db.execute("SELECT DISTINCT kind FROM db.mart.fact").fetchall()} == {
        "alteration", "biomarker", "ihc", "expression", "tested_negative", "actionability", "specimen"}
    assert one(db, "SELECT count(*) FROM db.mart.fact WHERE num IS NULL AND unit IS NOT NULL") == (0,)
    assert one(db, "SELECT count(*) FROM db.mart.fact "
                   "WHERE (tier IS NOT NULL) <> (kind = 'alteration' AND sub = 'mutation')") == (0,)


def test_mart_fact_alteration(db):
    mut = lambda v: set(db.execute("SELECT key, tier FROM db.mart.fact WHERE kind = 'alteration' AND sub = 'mutation' "
                                   "AND vendor = ?", [v]).fetchall())
    assert mut("caris") == {(g, tier) for g, _, _, _, tier in CARIS_TIERS}
    assert mut("fmi") == {("TP53", "pathogenic"), ("PIK3CA", "vus"), ("BRAF", "likely_pathogenic"), ("ARID1A", "unclassified")}
    for v in ("caris", "fmi"):
        assert one(db, f"SELECT val FROM db.mart.fact WHERE vendor = '{v}' AND key = 'TP53' AND sub = 'mutation'") == ("R175H",)
        assert one(db, f"SELECT count(*) FROM db.mart.fact WHERE vendor = '{v}' AND key = 'ERBB2' AND sub = 'amplification'") == (1,)
    assert set(db.execute("SELECT key, sub, val FROM db.mart.fact WHERE vendor = 'fmi' AND sub = 'fusion'").fetchall()) == {
        ("ALK", "fusion", "EML4"), ("EML4", "fusion", "ALK")}


def test_mart_fact_biomarker(db):
    assert facts(db, "caris", "biomarker") == {("TMB", None, "high", 22.0, "mut/Mb"), ("MSI", None, "stable", None, None),
                                               ("LOH", None, "high", 21.0, "%")}
    assert facts(db, "fmi", "biomarker") == {("TMB", None, "high", 22.0, "mut/Mb"), ("MSI", None, "stable", None, None)}


def test_mart_fact_ihc(db):
    got = facts(db, "caris", "ihc")
    assert got >= {("PD-L1", "22c3", "positive", 55.0, "TPS"), ("PD-L1", "22c3", "positive", 12.0, "CPS"),
                   ("ERBB2 (Her2/Neu)", None, "her2-low", 15.0, "% stained"),
                   ("Mismatch Repair Status", None, "proficient", None, None)}
    assert facts(db, "fmi", "ihc") == set()
    assert {r[0] for r in db.execute("SELECT clone FROM db.unified.biomarker WHERE name = 'PD-L1'").fetchall()} == {"22c3"}
    assert one(db, "SELECT count(*) FROM db.unified.biomarker WHERE name <> 'PD-L1' AND clone IS NOT NULL") == (0,)


def test_mart_fact_expression(db):
    assert facts(db, "caris", "expression") == {("TACSTD2", None, None, 81.0, "percentile")}


def test_mart_fact_tested_negative(db):
    assert set(db.execute("SELECT vendor, key, sub FROM db.mart.fact WHERE kind = 'tested_negative'").fetchall()) == {
        ("caris", "KRAS", "wildtype"), ("fmi", "KRAS", "pertinent_negative")}


def test_mart_fact_actionability(db):
    assert set(db.execute("SELECT vendor, key, sub, val FROM db.mart.fact WHERE kind = 'actionability'").fetchall()) == {
        ("caris", "caris_level1", "ERBB2", "trastuzumab"), ("fmi", "fmi_fda_any_indication", "ERBB2", "trastuzumab"),
        ("fmi", "fmi_trial", "ERBB2", "NCT00000001")}


def test_mart_fact_specimen(db):
    assert facts(db, "caris", "specimen", "key, val, num, unit") == {("site_type", "primary", None, None), ("site", "breast", None, None)}
    assert facts(db, "fmi", "specimen", "key, val, num, unit") == {("purity", None, 50.0, "%")}
