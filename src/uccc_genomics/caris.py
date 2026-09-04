"""Caris: mirror report JSON + gene TPM CSVs from S3, load into schema `caris`.

Idempotent: drops and rebuilds every caris.* table from the mirror (~15 min,
dominated by the TPM CSV read).
"""
import glob
import json
import os
import subprocess
import sys

from .config import CARIS_BUCKET, PHI_DB, PHI_DB_KEY, RAW, connect, sql
from .db import bulk_insert

RAW_CARIS = f"{RAW}/caris"


def sync():
    subprocess.run(["aws", "s3", "sync", CARIS_BUCKET, RAW_CARIS + "/", "--only-show-errors",
                    "--exclude", "*", "--include", "*.json", "--include", "*geneTPM_nodup.csv"], check=True)

DDL = """
CREATE TABLE report (
  case_id VARCHAR PRIMARY KEY, test_code VARCHAR, report_type VARCHAR,
  ordered_at TIMESTAMP, received_at TIMESTAMP, approved_at TIMESTAMP, approved_by VARCHAR,
  schema_version VARCHAR, report_version VARCHAR,
  mrn VARCHAR, dob DATE, gender VARCHAR, icd_code VARCHAR, diagnosis VARCHAR,
  pathologic_diagnosis VARCHAR, primary_site VARCHAR, lineage VARCHAR, sub_lineage VARCHAR,
  patient JSON, physician JSON, pathologist JSON, organization JSON, therapies JSON,
  source_file VARCHAR);
CREATE TABLE specimen (
  case_id VARCHAR, specimen_kind VARCHAR, specimen_idx INT, specimen_id VARCHAR,
  accession_id VARCHAR, specimen_type VARCHAR, site VARCHAR, site_type VARCHAR,
  age_at_collection INT, collected_on DATE, received_on DATE, extra JSON);
CREATE TABLE test (
  case_id VARCHAR, test_idx INT, test_name VARCHAR, test_code VARCHAR,
  platform_technology VARCHAR, methodology VARCHAR, specimen_id VARCHAR, n_results INT);
CREATE TABLE result (
  case_id VARCHAR, test_idx INT, result_idx INT, kind VARCHAR,
  biomarker_name VARCHAR, gene VARCHAR, result VARCHAR, result_group VARCHAR,
  genomic_source VARCHAR, interpretation VARCHAR, payload JSON);
"""

IMAGE_KINDS = {"eKarotypeGraph", "eGPSImagePath"}  # base64 PNGs; not loaded


def as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def j(x):
    return json.dumps(x) if x is not None else None


def rows_for(path):
    d = json.load(open(path))
    td, pt = d.get("testDetails", {}), d.get("patientInformation", {})
    case_id = td["labReportID"]
    report = (
        case_id, td.get("testCode"), td.get("reportType"),
        td.get("orderedDate"), td.get("receivedDate"),
        td.get("approvalInformation", {}).get("approveDate"),
        td.get("approvalInformation", {}).get("approvedBy"),
        td.get("labSchemaVersion"), td.get("labReportVersion"),
        pt.get("mrn"), pt.get("dob"), pt.get("gender"), pt.get("icd_code"), pt.get("diagnosis"),
        pt.get("pathologicDiagnosis"), pt.get("primarySite"), pt.get("lineage"), pt.get("subLineage"),
        j(pt), j(d.get("physicianInformation")), j(d.get("pathologistInformation")),
        j(d.get("healthcareOrganization")), j(d.get("therapies")),
        os.path.relpath(path, RAW),
    )
    specimens = []
    for kind, key in (("tumor", "tumorSpecimenInformation"), ("liquidBiopsy", "liquidBiopsySpecimenInformation")):
        for i, s in enumerate(as_list(d.get("specimenInformation", {}).get(key))):
            specimens.append((
                case_id, kind, i, s.get("specimenID"), s.get("specimenAccessionID"),
                s.get("specimenType"), s.get("specimenSite"), s.get("specimenSiteType"),
                s.get("patientAgeatCollection"), s.get("specimenCollectionDate"),
                s.get("specimenReceivedDate"), j(s),
            ))
    tests, results = [], []
    for ti, t in enumerate(as_list(d.get("tests"))):
        if not isinstance(t, dict):
            continue
        recs = [r for r in as_list(t.get("testResults")) if isinstance(r, dict)]
        tests.append((
            case_id, ti, t.get("testName"), t.get("testCode"), t.get("platformTechnology"),
            t.get("testMethodology"), (t.get("tumorSpecimenInformation") or {}).get("specimenID"), len(recs),
        ))
        for ri, r in enumerate(recs):
            (kind, v), = r.items()
            if kind in IMAGE_KINDS or not isinstance(v, dict):
                continue
            results.append((
                case_id, ti, ri, kind, v.get("biomarkerName"), v.get("gene"), v.get("result"),
                v.get("result_group"), v.get("genomicSource"), v.get("interpretation"), j(v),
            ))
    return report, specimens, tests, results


def load():
    # ponytail: newest JSON per case wins (Addended/Corrected re-deliveries supersede);
    # older versions remain in the raw mirror if anyone needs history
    files = sorted({os.path.dirname(f): f for f in sorted(glob.glob(f"{RAW_CARIS}/*/*.json"))}.values())
    if not files:
        sys.exit(f"no JSON under {RAW_CARIS} — run `genomics sync --vendor caris` first")
    con = connect(phi=(PHI_DB, PHI_DB_KEY))
    con.execute("CREATE SCHEMA IF NOT EXISTS caris; USE phi.caris")
    for t in ("report", "specimen", "test", "result", "gene_tpm"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute(DDL)
    R, S, T, X = [], [], [], []
    for f in files:
        r, s, t, x = rows_for(f)
        R.append(r); S += s; T += t; X += x
    for table, rows in (("report", R), ("specimen", S), ("test", T), ("result", X)):
        bulk_insert(con, table, rows)
    # ponytail: one read_csv over all files; ~150M rows, fine for a local DuckDB
    con.execute(f"""
        CREATE TABLE gene_tpm AS
        SELECT regexp_extract(filename, '(TN\\d+-\\d+)', 1) AS case_id,
               regexp_extract(filename, '/([A-Za-z]+)_TN', 1) AS assay,
               Gene AS gene, TPM::DOUBLE AS tpm, NumReads::DOUBLE AS num_reads
        FROM read_csv('{RAW_CARIS}/*/*geneTPM_nodup.csv', filename=true, union_by_name=true)
    """)
    con.execute(sql("caris_views.sql"))
    for t in ("report", "specimen", "test", "result", "gene_tpm"):
        print(f"{t:10s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>12,}")
    con.close()

