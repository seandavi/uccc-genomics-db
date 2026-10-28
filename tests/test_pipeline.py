"""load -> deid -> unified.* on synthetic Caris JSON and FMI XML in a temporary $DATA.

One patient (same MRN) tested by both vendors, one alteration of each kind, one wild-type /
pertinent-negative gene, so every unified view has something to assert on. No real data,
no network: `sync` is not exercised except FMI's, which runs against a fake `ssh`.
"""
import copy
import csv
import json
import os
import re
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
    ("BRIP1", "Mutated, Variant of Uncertain Significance", None, "p.A910T", "vus"),
    ("KMT2D", None, None, "p.A920T", "unclassified"),
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
                   # no score: value NULL while unified.biomarker.unit is '% stained', so mart.fact must null the unit
                   {"expressionAlteration": {"biomarkerName": "PD-L1 (SP142)", "result": "Positive", "expressionType": "IHC"}},
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
    <Interpretation>TP53 R175H was reviewed.</Interpretation>
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

def _gene(name, *alterations):
    """Genes-block <Gene> for FMI_GENES_ONLY: each alteration is (Alteration/Name, [AlterationProperty attribute strings])."""
    alts = "".join(
        f"<Alteration><Name>{n}</Name><Include>true</Include>"
        + (f"<AlterationProperties>{''.join(f'<AlterationProperty {p}/>' for p in props)}</AlterationProperties>" if props else "")
        + "</Alteration>" for n, props in alterations)
    return f"<Gene><Name>{name}</Name><Alterations>{alts}</Alterations></Gene>"


# An older report (#76): variants only in the Genes block, an empty <short-variants/> and no CNA elements.
FMI_GENES_ONLY = f"""<?xml version="1.0"?>
<ResultsReport>
 <FinalReport>
  <ReportId>ORD-0009876-01</ReportId><SampleName>ORD-0009876-01</SampleName><Version>1</Version>
  <Sample><TestType>FoundationOne</TestType><SpecFormat>FFPE</SpecFormat><ReceivedDate>2026-02-10</ReceivedDate></Sample>
  <PMI><MRN>0000555555</MRN><DOB>1940-05-06</DOB><Gender>Male</Gender><FirstName>John</FirstName><LastName>Roe</LastName>
       <FullName>John Roe</FullName><CollDate>2026-01-20</CollDate><SubmittedDiagnosis>Lung adenocarcinoma</SubmittedDiagnosis>
       <OrderingMD>Dr Other</OrderingMD><OrderingMDId>888</OrderingMDId><MedFacilName>UCH</MedFacilName><SpecSite>Lung</SpecSite></PMI>
  <Genes>
   {_gene("TP53", ("R248Q", ['name="R248Q" dnaFraction="42.0" isEquivocal="false" isSubclonal="false"']))}
   {_gene("PIK3CA", ("E545K, H1047R", ['name="E545K" dnaFraction="12"', 'name="H1047R" dnaFraction="0.5" isSubclonal="true"']))}
   {_gene("KMT2C (MLL3)", ("R100*", []))}
   {_gene("TERT", ("promoter -124C>T", ['name="promoter -124C>T" dnaFraction=""']))}
   {_gene("RB1", ("splice site 2107-2A>G", []))}
   {_gene("CDKN2A/B", ("p16INK4a R58* and p14ARF P72L", []), ("CDKN2B loss", []), ("loss", []))}
   {_gene("ERBB2", ("amplification", ['name="amplification" isEquivocal="true"']))}
   {_gene("PTEN", ("loss exons 6-9", []))}
   {_gene("WT1", ("rearrangement intron 1", []))}
   {_gene("KRAS", ("wildtype", []))}
   {_gene("Tumor Mutation Burden", ("TMB-Low", []))}
   {_gene("Microsatellite status", ("MS-Stable", []))}
  </Genes>
  <VariantProperties>
   <VariantProperty geneName="PIK3CA" variantName="H1047R" isVUS="true"/>
   <VariantProperty geneName="KMT2C (MLL3)" variantName="R100*" isVUS="true"/>
   <VariantProperty geneName="ARID1A" variantName="Q200*" isVUS="true"/>
   <VariantProperty geneName="KMT2D (MLL2)" variantName="R50fs*3" isVUS="true"/>
   <VariantProperty geneName="NF1" variantName="splice site 100+1G>A" isVUS="true"/>
   <VariantProperty geneName="TERT" variantName="promoter -146C>T" isVUS="true"/>
   <VariantProperty geneName="CDKN2A/B" variantName="p16INK4a A57V" isVUS="true"/>
   <VariantProperty geneName="CDKN2A/B" variantName="P114L" isVUS="true"/>
   <VariantProperty geneName="CDKN2A/B" variantName="p16INK4a loss and p14ARF loss exons 1-2" isVUS="true"/>
   <VariantProperty geneName="MYC" variantName="amplification" isVUS="true"/>
   <VariantProperty geneName="NOTCH1" variantName="rearrangement intron 2" isVUS="true"/>
   <VariantProperty geneName="BRCA2" variantName="E100K" isVUS="false"/>
   <VariantProperty geneName="BRCA1" variantName="D20N"/>
  </VariantProperties>
 </FinalReport>
 <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external"
     disease="Lung" disease-ontology="Lung adenocarcinoma" gender="male" test-type="FoundationOne">
  <samples><sample name="ORD-0009876-01" bait-set="F1" nucleic-acid-type="DNA" mean-exon-depth="500"/></samples>
  <short-variants/>
 </variant-report>
</ResultsReport>
"""

# FoundationOne Monitor files have no FinalReport (no PMI, no VariantProperties), so is_vus is NULL.
FMI_MONITOR = """<?xml version="1.0"?>
<ResultsReport>
 <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external"
     disease="Breast" disease-ontology="Breast carcinoma (NOS)" gender="female" test-type="FoundationOne Monitor">
  <short-variants>
   <short-variant gene="KRAS" cds-effect="35G>A" protein-effect="G12D" status="known" functional-effect="missense"/>
   <short-variant gene="NRAS" cds-effect="181C>A" protein-effect="Q61K" status="likely" functional-effect="missense"/>
   <short-variant gene="TP53" cds-effect="818G>A" protein-effect="R273H" status="unknown" functional-effect="missense"/>
   <short-variant gene="EGFR" cds-effect="2369C>T" protein-effect="T790M" status="new-fmi-status" functional-effect="missense"/>
  </short-variants>
 </variant-report>
</ResultsReport>
"""


def with_customer_information(xml, mrn):
    """`xml` with a ResultsReport/CustomerInformation block (FMI's children, synthetic values) carrying `mrn` (#89)."""
    return xml.replace("<ResultsReport>", "<ResultsReport>\n <CustomerInformation><CSN>9000001</CSN>"
                       f"<MRN>{mrn}</MRN><NPI>1234567890</NPI><PhysicianId>999</PhysicianId>"
                       "<ReferenceID>REF-1</ReferenceID><TRF>TRF00001</TRF></CustomerInformation>", 1)


def fmi_report(rid, mrn=MRN, full=True, ci_mrn=None):
    """FMI as report `rid` for patient `mrn`; full=False is the reduced copy (no <variant-report>);
    ci_mrn adds a CustomerInformation block carrying that MRN."""
    xml = FMI.replace("ORD-0001234-01", rid).replace(f"<MRN>{MRN}</MRN>", f"<MRN>{mrn}</MRN>")
    xml = xml if full else re.sub(r"\s*<variant-report.*</variant-report>", "", xml, flags=re.S)
    return xml if ci_mrn is None else with_customer_information(xml, ci_mrn)


# (case id, specimenSite, gene TPM file assays, has a wtsExpression record, has_wts): one Caris case per
# has_wts source, so dropping either arm of mart.sql's `wts` CTE, or its assay filter, fails a case.
WTS_CASES = [
    ("TN26-200001", "Liver", ["RNA"], False, True),
    ("TN26-200002", "Lung", ["cfTNA"], False, True),
    ("TN26-200003", "Colon", [], True, True),
    ("TN26-200004", "Brain", ["gDNA"], False, False),
]


def caris_case(case_id, site, wts_expression):
    """CARIS as another patient's case `case_id` at `site`, keeping or dropping its wtsExpression record."""
    c = copy.deepcopy(CARIS)
    c["testDetails"]["labReportID"] = case_id
    c["patientInformation"]["mrn"] = "000" + case_id[-6:]
    spec = c["specimenInformation"]["tumorSpecimenInformation"]
    spec["specimenID"], spec["specimenSite"] = f"{case_id}-A", site
    if not wts_expression:
        c["tests"][0]["testResults"] = [r for r in c["tests"][0]["testResults"] if "wtsExpression" not in r]
    return c


def genomics(data_dir, *args):
    subprocess.run(["uv", "run", "genomics", *args], check=True, cwd=ROOT, capture_output=True, text=True,
                   env={**os.environ, "DATA": data_dir})


def pipeline(data, fmi_files, caris_cases=None):
    """Write `caris_cases` ({case id: (report JSON, gene TPM file assays)}, default CARIS with an RNA
    TPM file) and `fmi_files` ({file name: XML text}) under raw/ in `data`, run load for both vendors
    and deid, and return a connection with the de-id file attached as `db` and the PHI file as `phi`,
    both read-only."""
    os.makedirs(f"{data}/raw/fmi")
    for case_id, (report, assays) in (caris_cases or {"TN26-123456": (CARIS, ["RNA"])}).items():
        case = f"{data}/raw/caris/{case_id}"
        os.makedirs(case)
        json.dump(report, open(f"{case}/{case_id}.json", "w"))
        for assay in assays:
            with open(f"{case}/{assay}_{case_id}_geneTPM_nodup.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Gene", "TPM", "NumReads"])
                w.writerows([["TP53", "12.5", "800"], ["ERBB2", "300.1", "9000"]])
    for name, text in fmi_files.items():
        open(f"{data}/raw/fmi/{name}", "w").write(text)

    genomics(data, "load", "--vendor", "caris")
    genomics(data, "load", "--vendor", "fmi")
    genomics(data, "deid")

    con = duckdb.connect()
    for alias, name, key in (("db", "genomics.duckdb", ".db_key"), ("phi", "genomics_phi.duckdb", ".db_key_phi")):
        con.execute(f"ATTACH '{data}/{name}' AS {alias} (ENCRYPTION_KEY '{open(f'{data}/{key}').read().strip()}', READ_ONLY)")
    return con


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    # broken.xml must fail to parse and land in fmi.load_error rather than abort the load.
    return pipeline(str(tmp_path_factory.mktemp("data")),
                    {"ORD-0001234-01.xml": FMI, "broken.xml": "<ResultsReport><nothing/></ResultsReport>"})


@pytest.fixture(scope="module")
def genes_db(tmp_path_factory):
    return pipeline(str(tmp_path_factory.mktemp("genes")),
                    {"ORD-0001234-01.xml": FMI, "ORD-0009876-01.xml": FMI_GENES_ONLY})


@pytest.fixture(scope="module")
def dup_db(tmp_path_factory):
    # A: reduced copy sorts first ("." < "_"), written last (newer mtime, as on the share)
    # B: full file sorts first, written last (newer mtime)
    # C: one ReportId, two patients
    return pipeline(str(tmp_path_factory.mktemp("dup")), {
        "ORD-0002222-01_v2.xml": fmi_report("ORD-0002222-01"),
        "ORD-0002222-01.xml": fmi_report("ORD-0002222-01", full=False),
        "ORD-0003333-01_v2.xml": fmi_report("ORD-0003333-01", full=False),
        "ORD-0003333-01.xml": fmi_report("ORD-0003333-01"),
        "ORD-0004444-01.xml": fmi_report("ORD-0004444-01"),
        "ORD-0004444-01_v2.xml": fmi_report("ORD-0004444-01", mrn="0000777777"),
        "ORD-0005555-01.xml": fmi_report("ORD-0005555-01"),
        "ORD-0005555-01_v2.xml": fmi_report("ORD-0005555-01", mrn="", full=False, ci_mrn=MRN),
        "broken.xml": "<ResultsReport><nothing/></ResultsReport>"})


@pytest.fixture(scope="module")
def monitor_mrn_db(tmp_path_factory):
    return pipeline(str(tmp_path_factory.mktemp("monitor_mrn")), {
        "ORD-0001234-01.xml": FMI,
        "ORD-0005678-01.xml": with_customer_information(FMI_MONITOR, "000-123456"),
        "ORD-0005679-01.xml": FMI_MONITOR})


@pytest.fixture(scope="module")
def monitor_db(tmp_path_factory):
    return pipeline(str(tmp_path_factory.mktemp("monitor")), {"ORD-0005678-01.xml": FMI_MONITOR})


@pytest.fixture(scope="module")
def wts_db(tmp_path_factory):
    return pipeline(str(tmp_path_factory.mktemp("wts")), {"ORD-0005678-01.xml": FMI_MONITOR},
                    {c: (caris_case(c, site, wts), assays) for c, site, assays, wts, _ in WTS_CASES})


def one(con, sql):
    return con.execute(sql).fetchone()


def test_find_leaks_matches_embedded_and_lower_case_ids():
    from uccc_genomics.deid import find_leaks
    con = duckdb.connect()
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.fact AS SELECT * FROM (VALUES ('trastuzumab', 'see tn26-123456 notes'), "
                "('olaparib', NULL), ('x', 'ORD-0001234-01')) t(val, note)")
    assert find_leaks(con, ["mart"]) == ["mart.fact.note: 2"]
    assert find_leaks(con, ["caris"]) == []


def test_deid_replaces_file_only_after_leak_check(tmp_path):
    data = str(tmp_path)
    con = pipeline(data, {"ORD-0001234-01.xml": FMI})
    ids = con.execute("SELECT vendor, research_id FROM db.unified.report ORDER BY ALL").fetchall()
    con.close()
    path, tmp = f"{data}/genomics.duckdb", f"{data}/genomics.duckdb.tmp"
    first = os.stat(path)

    # A leftover temp file and WAL from an interrupted run are cleared, not attached
    for f in (tmp, f"{tmp}.wal"):
        open(f, "wb").write(b"not a duckdb file")
    genomics(data, "deid")
    good = os.stat(path)
    assert good.st_ino != first.st_ino  # renamed into place, not rewritten
    assert not os.path.exists(tmp) and not os.path.exists(f"{tmp}.wal")

    # An id embedded in FMI free text fails the leak check: the previous file stays
    open(f"{data}/raw/fmi/ORD-0001234-01.xml", "w").write(
        FMI.replace("TP53 R175H was reviewed.", "TP53 R175H ORD-0001234-01 was reviewed."))
    genomics(data, "load", "--vendor", "fmi")
    with pytest.raises(subprocess.CalledProcessError) as e:
        genomics(data, "deid")
    assert "identifier-like tokens survived de-identification" in e.value.stderr
    after = os.stat(path)
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (good.st_ino, good.st_mtime_ns, good.st_size)
    assert not os.path.exists(tmp) and not os.path.exists(f"{tmp}.wal")

    from uccc_genomics.deid import find_leaks
    con = duckdb.connect()
    con.execute(f"ATTACH '{path}' AS db (ENCRYPTION_KEY '{open(f'{data}/.db_key').read().strip()}', READ_ONLY)")
    con.execute("USE db")
    assert find_leaks(con, ["caris", "fmi", "mart"]) == []
    assert con.execute("SELECT vendor, research_id FROM unified.report ORDER BY ALL").fetchall() == ids


def test_same_mrn_is_one_patient_across_vendors(db):
    assert one(db, "SELECT count(*), max(n_vendors) FROM db.unified.patient") == (1, 2)
    assert one(db, "SELECT count(DISTINCT research_id), count(*) FROM db.unified.report") == (1, 2)


def test_phi_columns_are_gone_and_ids_are_hashed(db):
    cols = {r[0] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog='db' AND table_schema IN ('caris','fmi')").fetchall()}
    assert not cols & {"mrn", "dob", "first_name", "last_name", "patient", "physician", "ordering_md", "source_file", "pathologist_comment", "mrn_source"}
    assert one(db, "SELECT case_id FROM db.caris.report")[0] != "TN26-123456"
    assert one(db, "SELECT report_id FROM db.fmi.report")[0] != "ORD-0001234-01"
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
    # Caris tier and is_vus agree; no fixture row has a pathogenic term together with unknownSignificance.
    assert one(db, "SELECT count(*) FROM db.unified.variant "
                   "WHERE vendor = 'caris' AND coalesce(is_vus, false) <> (tier = 'vus')") == (0,)


def test_variant_tier_fmi_without_final_report(monitor_db):
    """Monitor files have no VUS list (is_vus NULL); tier still follows status, and an unlisted status is unclassified."""
    got = {r[0]: (r[1], r[2]) for r in monitor_db.execute(
        "SELECT gene, is_vus, tier FROM db.unified.variant WHERE vendor = 'fmi'").fetchall()}
    assert got == {"KRAS": (None, "pathogenic"), "NRAS": (None, "likely_pathogenic"),
                   "TP53": (None, "unclassified"), "EGFR": (None, "unclassified")}


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
               ("has_wts", "BOOLEAN"), ("collected_on", "DATE")]
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
                   "OR m.year_complete IS DISTINCT FROM u.collected_year_complete "
                   "OR m.collected_on IS DISTINCT FROM u.collected_on") == (0,)
    cols = "sex, age, age_band, oncotree, assay_class, site_type, site, has_wts, purity"
    assert one(db, f"SELECT {cols} FROM db.mart.report WHERE vendor = 'caris'") == (
        "female", 89, "75+", "BRCA", "tissue", "primary", "breast", True, None)
    assert one(db, f"SELECT {cols} FROM db.mart.report WHERE vendor = 'fmi'") == (
        "female", None, "unknown", "BRCA", "tissue", None, None, False, 50.0)


def test_mart_report_has_wts_per_source(wts_db):
    """RNA and cfTNA TPM files and wtsExpression records each make has_wts true on their own; a gDNA TPM file doesn't."""
    got = dict(wts_db.execute("SELECT site, has_wts FROM db.mart.report WHERE vendor = 'caris'").fetchall())
    assert got == {site.lower(): want for _, site, _, _, want in WTS_CASES}


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


GENES_ONLY = "ORD-0009876-01"


def test_genes_block_parsers():
    from uccc_genomics.fmi import genes_block_cna, genes_block_short_variant as sv
    cases = [  # (Gene/Name, part, short variant, copy-number call)
        ("TP53", "R175H", ("TP53", None, "R175H"), None),
        ("APC", "P72fs*9", ("APC", None, "P72fs*9"), None),
        ("KMT2C (MLL3)", "R100*", ("KMT2C", None, "R100*"), None),
        ("RB1", "splice site 2107-2A>G", ("RB1", "2107-2A>G", "splice site 2107-2A>G"), None),
        ("TERT", "promoter -124C>T", ("TERT", "-124C>T", "promoter -124C>T"), None),
        ("CDKN2A/B", "p16INK4a R58* and p14ARF P72L", ("CDKN2A", None, "R58*"), None),
        ("CDKN2A/B", "CDKN2B loss", None, ("CDKN2B", "loss")),
        ("CDKN2A/B", "loss", None, None),
        ("CDKN2A/B", "p16INK4a loss and p14ARF loss exons 1-2", None, None),
        ("ERBB2", "amplification", None, ("ERBB2", "amplification")),
        ("PTEN", "loss exons 6-9", None, ("PTEN", "loss")),
        ("STK11", "loss exon 2", None, ("STK11", "loss")),
        ("LRP1B", "deletion exons 15-25", None, None),
        ("WT1", "rearrangement intron 1", None, None),
        ("TMPRSS2", "TMPRSS2-ERG fusion", None, None),
        ("KRAS", "wildtype", None, None),
        ("Tumor Mutation Burden", "TMB-Low", None, None),
        ("Tumor Mutation Burden", "01", None, None),
        ("Microsatellite status", "MS-Stable", None, None),
        ("HRD signature", "HRDsig Negative", None, None),
        (None, "R175H", None, None),
    ]
    for gene, part, want_sv, want_cna in cases:
        assert sv(gene, part) == want_sv, (gene, part)
        assert genes_block_cna(gene, part) == want_cna, (gene, part)


def test_fmi_genes_block_short_variants(genes_db):
    rows = genes_db.execute(
        "SELECT gene, cds_effect, protein_effect, round(allele_fraction, 6), equivocal, subclonal, is_vus, status, depth, source "
        "FROM phi.fmi.short_variant WHERE report_id = ? AND source = 'genes_block'", [GENES_ONLY]).fetchall()
    assert {r[:7] for r in rows} == {
        ("TP53", None, "R248Q", 0.42, False, False, False),
        ("PIK3CA", None, "E545K", 0.12, None, None, False),     # property has only dnaFraction
        ("PIK3CA", None, "H1047R", 0.005, None, True, True),
        ("KMT2C", None, "R100*", None, None, None, True),       # VUS listed under the aliased gene
        ("TERT", "-124C>T", "promoter -124C>T", None, None, None, False),   # empty dnaFraction
        ("RB1", "2107-2A>G", "splice site 2107-2A>G", None, None, None, False),
        ("CDKN2A", None, "R58*", None, None, None, False)}
    assert len(rows) == 7
    assert {r[7:] for r in rows} == {(None, None, "genes_block")}


def test_fmi_variant_properties_vus(genes_db):
    rows = genes_db.execute(
        "SELECT gene, cds_effect, protein_effect, is_vus, position, transcript, strand, allele_fraction, depth, "
        "percent_reads, status, functional_effect, equivocal, subclonal "
        "FROM phi.fmi.short_variant WHERE report_id = ? AND source = 'variant_properties'", [GENES_ONLY]).fetchall()
    assert {r[:3] for r in rows} == {
        ("ARID1A", None, "Q200*"), ("KMT2D", None, "R50fs*3"), ("NF1", "100+1G>A", "splice site 100+1G>A"),
        ("TERT", "-146C>T", "promoter -146C>T"), ("CDKN2A", None, "A57V")}
    assert len(rows) == 5
    assert genes_db.execute("SELECT count(*), min(source) FROM phi.fmi.short_variant WHERE report_id = ? "
                            "AND gene = 'KMT2C' AND protein_effect = 'R100*'", [GENES_ONLY]).fetchone() == (1, "genes_block")
    assert all(r[3] is True and r[4:] == (None,) * 10 for r in rows)
    assert genes_db.execute("SELECT count(*), min(source) FROM phi.fmi.short_variant WHERE report_id = ? "
                            "AND gene = 'PIK3CA' AND protein_effect = 'H1047R'", [GENES_ONLY]).fetchone() == (1, "genes_block")
    assert genes_db.execute("SELECT count(*) FROM phi.fmi.short_variant WHERE report_id = ? AND (gene IN "
                            "('BRCA1', 'BRCA2', 'MYC', 'NOTCH1') OR protein_effect = 'P114L')", [GENES_ONLY]).fetchone() == (0,)
    assert genes_db.execute("SELECT count(*) FROM phi.fmi.cna WHERE report_id = ? AND gene = 'MYC'", [GENES_ONLY]).fetchone() == (0,)
    assert one(genes_db, "SELECT count(*) FROM phi.fmi.short_variant WHERE report_id = 'ORD-0001234-01' "
                         "AND source = 'variant_properties'") == (0,)


def test_fmi_genes_block_cna(genes_db):
    assert set(genes_db.execute("SELECT gene, type, equivocal, source FROM phi.fmi.cna WHERE report_id = ?",
                                [GENES_ONLY]).fetchall()) == {
        ("ERBB2", "amplification", True, "genes_block"), ("CDKN2B", "loss", None, "genes_block"),
        ("PTEN", "loss", None, "genes_block")}


def test_fmi_genes_block_not_duplicated(genes_db):
    """ORD-0001234-01 has the elements and also lists TP53 R175H / ERBB2 amplification in its Genes block."""
    for table, n in (("short_variant", 4), ("cna", 1)):
        assert genes_db.execute(f"SELECT count(*), count(*) FILTER (WHERE source = 'variant_report') "
                                f"FROM phi.fmi.{table} WHERE report_id = 'ORD-0001234-01'").fetchone() == (n, n)
    assert one(genes_db, "SELECT count(*) FROM phi.fmi.alteration WHERE report_id = 'ORD-0009876-01'") == (14,)


def test_fmi_genes_block_rule_is_per_table(tmp_path):
    """A report with <short-variant> but no <copy-number-alteration> gets Genes-block CNA only."""
    from uccc_genomics.fmi import rows_for
    xml = f"""<?xml version="1.0"?>
<ResultsReport>
 <FinalReport>
  <ReportId>ORD-0007777-01</ReportId><SampleName>ORD-0007777-01</SampleName><Version>1</Version>
  <Genes>
   {_gene("TP53", ("R175H", []))}
   {_gene("ERBB2", ("amplification", []))}
  </Genes>
  <VariantProperties><VariantProperty geneName="ARID1A" variantName="Q200*" isVUS="true"/></VariantProperties>
 </FinalReport>
 <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external">
  <short-variants><short-variant gene="TP53" cds-effect="524G>A" protein-effect="R175H" status="known"/></short-variants>
 </variant-report>
</ResultsReport>
"""
    path = tmp_path / "ORD-0007777-01.xml"
    path.write_text(xml)
    _, t = rows_for(str(path))
    assert t["cna"] == [("ORD-0007777-01", "ERBB2", "amplification", None, None, None, None, None, None, "genes_block")]
    assert [r[-1] for r in t["short_variant"]] == ["variant_report"]


def test_fmi_genes_block_tier(genes_db):
    got = set(genes_db.execute("SELECT gene, hgvs_p, tier FROM db.unified.variant WHERE source = 'genes_block'").fetchall())
    want = {(g, p, "likely_pathogenic") for g, p in (("TP53", "R248Q"), ("PIK3CA", "E545K"),
            ("TERT", "promoter -124C>T"), ("RB1", "splice site 2107-2A>G"), ("CDKN2A", "R58*"))}
    assert got == want | {("PIK3CA", "H1047R", "vus"), ("KMT2C", "R100*", "vus")}
    assert genes_db.execute("SELECT DISTINCT tier FROM db.unified.variant WHERE source = 'variant_properties'").fetchall() == [("vus",)]
    assert set(genes_db.execute("SELECT gene, tier FROM db.unified.variant WHERE source = 'variant_report'").fetchall()) == {
        ("TP53", "pathogenic"), ("PIK3CA", "vus"), ("BRAF", "likely_pathogenic"), ("ARID1A", "unclassified")}
    assert one(genes_db, "SELECT count(*) FROM db.unified.variant WHERE vendor = 'caris' AND source IS NOT NULL") == (0,)
    assert one(genes_db, "SELECT count(*) FROM db.unified.cna WHERE vendor = 'caris' AND source IS NOT NULL") == (0,)
    assert one(genes_db, "SELECT count(*) FROM db.unified.cna WHERE source = 'genes_block'") == (3,)


def test_mart_fact_genes_block(genes_db):
    fact = set(genes_db.execute(
        "SELECT key, sub, val, tier FROM db.mart.fact WHERE vendor = 'fmi' AND kind = 'alteration' "
        "AND report_id IN (SELECT report_id FROM db.unified.cna WHERE source = 'genes_block')").fetchall())
    assert ("TP53", "mutation", "R248Q", "likely_pathogenic") in fact
    assert ("PIK3CA", "mutation", "H1047R", "vus") in fact
    assert ("ARID1A", "mutation", "Q200*", "vus") in fact
    assert ("KMT2D", "mutation", "R50fs*3", "vus") in fact
    assert {k for k, sub, _, _ in fact if sub == "amplification"} == {"ERBB2"}
    assert {k for k, sub, _, _ in fact if sub == "loss"} == {"PTEN", "CDKN2B"}
    assert not {k for k, *_ in fact} & {"Tumor Mutation Burden", "Microsatellite status", "WT1", "KRAS"}


def test_mart_fact_biomarker(db):
    assert facts(db, "caris", "biomarker") == {("TMB", None, "high", 22.0, "mut/Mb"), ("MSI", None, "stable", None, None),
                                               ("LOH", None, "high", 21.0, "%")}
    assert facts(db, "fmi", "biomarker") == {("TMB", None, "high", 22.0, "mut/Mb"), ("MSI", None, "stable", None, None)}


def test_mart_fact_ihc(db):
    got = facts(db, "caris", "ihc")
    assert got >= {("PD-L1", "22c3", "positive", 55.0, "TPS"), ("PD-L1", "22c3", "positive", 12.0, "CPS"),
                   ("PD-L1", "sp142", "positive", None, None),
                   ("ERBB2 (Her2/Neu)", None, "her2-low", 15.0, "% stained"),
                   ("Mismatch Repair Status", None, "proficient", None, None)}
    assert facts(db, "fmi", "ihc") == set()
    assert {r[0] for r in db.execute("SELECT clone FROM db.unified.biomarker WHERE name = 'PD-L1'").fetchall()} == {"22c3", "sp142"}
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


def fake_ssh(tmp_path):
    """Write a fake `ssh` that drops its options and host and runs the remote command locally."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text('#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\nsh -c "$1"; rc=$?\n'
                   'exit "${FAKE_SSH_EXIT:-$rc}"\n')
    ssh.chmod(0o755)
    return str(bin_dir)


def fmi_sync(data, src, bin_dir, **env):
    return subprocess.run(["uv", "run", "genomics", "sync", "--vendor", "fmi"], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "DATA": data, "FMI_SRC": f"fakehost:{src}",
                               "PATH": f"{bin_dir}:{os.environ['PATH']}", **env})


def test_fmi_sync_copies_xml(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.xml").write_text(FMI)
    (src / "B.xml").write_text("<x/>")
    r = fmi_sync(str(tmp_path / "data"), src, fake_ssh(tmp_path))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "data/raw/fmi/A.xml").read_text() == FMI
    assert (tmp_path / "data/raw/fmi/B.xml").read_text() == "<x/>"


def test_fmi_sync_fails_on_empty_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    mirror = tmp_path / "data/raw/fmi"
    mirror.mkdir(parents=True)
    (mirror / "old.xml").write_text("<old/>")
    r = fmi_sync(str(tmp_path / "data"), src, fake_ssh(tmp_path))
    assert r.returncode != 0
    assert "no *.xml in " in r.stderr
    assert (mirror / "old.xml").read_text() == "<old/>"


def test_fmi_sync_fails_on_missing_source(tmp_path):
    r = fmi_sync(str(tmp_path / "data"), tmp_path / "nope", fake_ssh(tmp_path))
    assert r.returncode != 0


def test_fmi_sync_fails_when_remote_fails(tmp_path):
    # The archive streams fine, so only the ssh exit status catches it (#75).
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.xml").write_text("<x/>")
    r = fmi_sync(str(tmp_path / "data"), src, fake_ssh(tmp_path), FAKE_SSH_EXIT="2")
    assert r.returncode != 0


def test_check_flags_stale_vendor(tmp_path):
    pipeline(str(tmp_path), {"ORD-0001234-01.xml": FMI}).close()
    fmi_age = (date.today() - date(2026, 1, 10)).days  # Caris received 3 days earlier

    def check(stale_days, *args):
        return subprocess.run(["uv", "run", "genomics", "check", *args], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "DATA": str(tmp_path), "STALE_DAYS": stale_days})

    r = check(str(fmi_age))
    assert r.returncode != 0
    assert r.stderr.splitlines()[-1] == f"stale vendor data: caris (newest received date older than {fmi_age} days)"
    assert f"== check fmi: newest received date is {fmi_age} days old" in r.stderr
    assert "2026-01" not in r.stderr
    assert check(str(fmi_age + 3)).returncode == 0
    assert check(str(fmi_age), "--vendor", "fmi").returncode == 0
    r = check("")
    assert r.returncode != 0
    assert "(limit 21)" in r.stderr


def test_fmi_duplicate_report_loads_full_file(dup_db):
    assert set(dup_db.execute("SELECT report_id, source_file FROM phi.fmi.report").fetchall()) == {
        ("ORD-0002222-01", "fmi/ORD-0002222-01_v2.xml"), ("ORD-0003333-01", "fmi/ORD-0003333-01.xml"),
        ("ORD-0005555-01", "fmi/ORD-0005555-01.xml")}
    for rid in ("ORD-0002222-01", "ORD-0003333-01", "ORD-0005555-01"):
        for table, n in (("short_variant", 4), ("cna", 1)):
            assert dup_db.execute(f"SELECT count(*), count(*) FILTER (WHERE source = 'variant_report') "
                                  f"FROM phi.fmi.{table} WHERE report_id = ?", [rid]).fetchone() == (n, n)
        for table, n in (("rearrangement", 1), ("alteration", 2), ("therapy", 4), ("trial", 2), ("pertinent_negative", 1)):
            assert one(dup_db, f"SELECT count(*) FROM phi.fmi.{table} WHERE report_id = '{rid}'") == (n,)
        assert dup_db.execute("SELECT count(*), bool_and(is_vus) FROM phi.fmi.short_variant WHERE report_id = ? "
                              "AND gene = 'PIK3CA' AND protein_effect = 'E545K'", [rid]).fetchone() == (1, True)


def test_fmi_duplicate_file_log(dup_db):
    assert set(dup_db.execute("SELECT file, chosen_file, reason FROM phi.fmi.duplicate_file").fetchall()) == {
        ("fmi/ORD-0002222-01.xml", "fmi/ORD-0002222-01_v2.xml", "variant_elements"),
        ("fmi/ORD-0003333-01_v2.xml", "fmi/ORD-0003333-01.xml", "variant_elements"),
        ("fmi/ORD-0005555-01_v2.xml", "fmi/ORD-0005555-01.xml", "variant_elements")}
    errors = dict(dup_db.execute("SELECT file, error FROM phi.fmi.load_error").fetchall())
    conflict = "ValueError: conflicting patient identity for report_id ORD-0004444-01"
    assert errors["fmi/ORD-0004444-01.xml"] == errors["fmi/ORD-0004444-01_v2.xml"] == conflict
    assert "fmi/broken.xml" in errors and len(errors) == 3
    assert not any("duplicate report_id" in e for e in errors.values())
    for table in ("report", "short_variant"):
        assert one(dup_db, f"SELECT count(*) FROM phi.fmi.{table} WHERE report_id = 'ORD-0004444-01'") == (0,)


def test_fmi_duplicate_deid(dup_db):
    tables = {r[0] for r in dup_db.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'db'").fetchall()}
    assert not tables & {"duplicate_file", "load_error"}
    ids = dup_db.execute("SELECT DISTINCT research_id FROM db.fmi.report").fetchall()
    assert len(ids) == 1 and ids == dup_db.execute("SELECT DISTINCT research_id FROM db.caris.report").fetchall()


def test_fmi_choice_tie_breaks(tmp_path):
    from uccc_genomics.fmi import CHOICE, choice_key, rows_for

    amendment = ("<Amendmends><Amendmend><ModifiedDts>2026-01-01T00:00:00</ModifiedDts><Type>Addendum</Type>"
                 "<IsSigned>true</IsSigned></Amendmend></Amendmends>")

    def key(name, xml, mtime):
        path = tmp_path / name
        path.write_text(xml)
        os.utime(path, (mtime, mtime))
        return choice_key(str(path), *rows_for(str(path)))

    def first_diff(a, b):
        assert a > b
        return next(n for n, x, y in zip(CHOICE, a, b) if x != y)

    reduced = fmi_report("ORD-0008888-01", full=False)
    t0 = 1_700_000_000
    for full_mtime in (t0, t0 + 200):  # full file older, then newer than the reduced copy
        assert first_diff(key("full.xml", fmi_report("ORD-0008888-01"), full_mtime),
                          key("reduced.xml", reduced, t0 + 100)) == "variant_elements"
    assert first_diff(key("v2.xml", reduced.replace("<Version>1</Version>", "<Version>2</Version>"), t0),
                      key("v1.xml", reduced, t0)) == "version"
    assert first_diff(key("amended.xml", reduced.replace("</FinalReport>", f"{amendment}</FinalReport>"), t0),
                      key("plain.xml", reduced, t0)) == "amendments"
    assert first_diff(key("new.xml", reduced, t0 + 100), key("old.xml", reduced, t0)) == "mtime"
    assert first_diff(key("b.xml", reduced, t0), key("a.xml", reduced, t0)) == "path"


def test_fmi_patient_identity(tmp_path):
    from uccc_genomics.fmi import patient_identity, rows_for

    def ident(xml):
        path = tmp_path / "r.xml"
        path.write_text(xml)
        return patient_identity(rows_for(str(path))[0])

    no_mrn = fmi_report("ORD-0007777-01", mrn="")
    names = "<FirstName>Jane</FirstName><LastName>Doe</LastName>"
    dob = "<DOB>1930-02-03</DOB>"
    # Literal value pins the order and the indices of last, first and DOB in the report tuple
    assert ident(no_mrn) == "doe|jane|1930-02-03"
    upper = no_mrn.replace(names, "<FirstName>JANE</FirstName><LastName>DOE</LastName>")
    assert upper != no_mrn                       # the replace hit, so the case check below is not vacuous
    assert ident(upper) == "doe|jane|1930-02-03"
    assert ident(fmi_report("ORD-0007777-01", mrn="N/A")) == "doe|jane|1930-02-03"  # no digits: no MRN
    # Each fallback field separates two MRN-less patients
    for other in (no_mrn.replace("<LastName>Doe<", "<LastName>Roe<"),
                  no_mrn.replace("<FirstName>Jane<", "<FirstName>Joan<"),
                  no_mrn.replace(dob, "<DOB>1931-02-03</DOB>")):
        assert ident(other) not in (None, ident(no_mrn))
    # MRN on one file, absent on the other: different identities
    assert ident(fmi_report("ORD-0007777-01")) == MRN != ident(no_mrn)
    # Any fallback field missing: None
    for missing in (no_mrn.replace(dob, ""), no_mrn.replace("<LastName>Doe</LastName>", ""),
                    no_mrn.replace("<FirstName>Jane</FirstName>", "")):
        assert ident(missing) is None


def test_fmi_mrn_fallback(tmp_path):
    from uccc_genomics.fmi import patient_identity, rows_for

    def parsed(xml):
        path = tmp_path / "r.xml"
        path.write_text(xml)
        return rows_for(str(path))[0]

    rid = "ORD-0007001-01"
    ci = "000-123456"
    for xml, want in (
            (fmi_report(rid, ci_mrn="0000999999"), (MRN, "pmi")),                      # PMI wins
            (fmi_report(rid, mrn="", ci_mrn=ci), (MRN, "customer_information")),
            (fmi_report(rid, mrn="N/A", ci_mrn=MRN), (MRN, "customer_information")),   # no digits: empty
            (with_customer_information(FMI_MONITOR, ci), (MRN, "customer_information")),
            (FMI_MONITOR, (None, None)),
            (with_customer_information(FMI_MONITOR, ""), (None, None)),
            (with_customer_information(FMI_MONITOR, "N/A"), (None, None)),
            (fmi_report(rid, mrn="", ci_mrn=""), (None, None)),
            (fmi_report(rid, mrn="N/A"), (None, None))):
        report = parsed(xml)
        assert (report[7], report[-1]) == want
    assert len(parsed(FMI_MONITOR)) == 39                                              # mrn_source is last
    assert patient_identity(parsed(fmi_report(rid, mrn="", ci_mrn=MRN))) == MRN


def test_fmi_monitor_links_by_customer_information_mrn(monitor_mrn_db):
    db = monitor_mrn_db
    assert set(db.execute("SELECT report_id, mrn, mrn_source FROM phi.fmi.report").fetchall()) == {
        ("ORD-0001234-01", MRN, "pmi"), ("ORD-0005678-01", MRN, "customer_information"),
        ("ORD-0005679-01", None, None)}
    assert sorted(n for _, n in db.execute("SELECT research_id, count(*) FROM db.unified.report GROUP BY 1").fetchall()) == [1, 3]
    assert one(db, "SELECT count(*) FROM db.unified.patient") == (2,)
    for catalog, n in (("db", 0), ("phi", 1)):
        assert one(db, "SELECT count(*) FROM information_schema.columns "
                       f"WHERE table_catalog = '{catalog}' AND column_name = 'mrn_source'") == (n,)


def test_fmi_vus_lookup_normalizes_names(tmp_path):
    from uccc_genomics.fmi import rows_for
    xml = """<?xml version="1.0"?>
<ResultsReport>
 <FinalReport>
  <ReportId>ORD-0006666-01</ReportId><SampleName>ORD-0006666-01</SampleName><Version>1</Version>
  <VariantProperties>
   <VariantProperty geneName="KMT2C (MLL3)" variantName="R100*" isVUS="true"/>
   <VariantProperty geneName="CDKN2A/B" variantName="p16INK4a A57V" isVUS="true"/>
  </VariantProperties>
 </FinalReport>
 <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external">
  <short-variants>
   <short-variant gene="KMT2C" cds-effect="298C>T" protein-effect="R100*" status="unknown"/>
   <short-variant gene="CDKN2A" cds-effect="170C>T" protein-effect="A57V" status="unknown"/>
   <short-variant gene="TP53" cds-effect="524G>A" protein-effect="R175H" status="known"/>
  </short-variants>
 </variant-report>
</ResultsReport>
"""
    path = tmp_path / "ORD-0006666-01.xml"
    path.write_text(xml)
    _, t = rows_for(str(path))
    assert {(r[1], r[3], r[14]) for r in t["short_variant"]} == {
        ("KMT2C", "R100*", True), ("CDKN2A", "A57V", True), ("TP53", "R175H", False)}
    assert {r[-1] for r in t["short_variant"]} == {"variant_report"}
