"""Framework data loader: every aggregate the dashboard shows, from one DB open, as one JSON.

Small-cell rule: any count below MIN_CELL is dropped here, before it leaves the loader.
Nothing row-level is emitted. Dates in the de-id file are already shifted per patient.
"""
import datetime
import json
import sys

from uccc_genomics.config import DEID_DB, DEID_DB_KEY, connect

MIN_CELL = 5
con = connect(db=(DEID_DB, DEID_DB_KEY, "READ_ONLY"))


def rows(sql: str) -> list[dict]:
    """Rows as dicts, minus any whose `n` is a small cell."""
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [r for r in out if r.get("n") is None or r["n"] >= MIN_CELL]


# One alteration row per (report, gene, type). VUS kept separate so it can be toggled.
ALT = """
WITH alt AS (
  SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type
  FROM unified.variant WHERE gene IS NOT NULL
  UNION ALL SELECT vendor, report_id, gene, cn_type FROM unified.cna WHERE cn_type IN ('amplification', 'loss')
  UNION ALL SELECT vendor, report_id, gene1, 'fusion' FROM unified.fusion WHERE gene1 IS NOT NULL
  UNION ALL SELECT vendor, report_id, gene2, 'fusion' FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1
),
rep AS (SELECT vendor, report_id, coalesce(disease_text, '(not stated)') AS disease FROM unified.report)
"""

summary = {
    "meta": rows("""
        SELECT count(*) AS n_reports, count(DISTINCT research_id) AS n_patients,
               (SELECT count(*) FROM unified.variant) AS n_variants,
               (SELECT count(*) FROM unified.cna) AS n_cna,
               (SELECT count(*) FROM unified.fusion) AS n_fusions,
               (SELECT count(*) FROM unified.patient WHERE n_vendors > 1) AS n_multi_vendor,
               max(coalesce(received_on, collected_on))::DATE AS last_received
        FROM unified.report""")[0]
    | {"built_at": datetime.datetime.now().isoformat(timespec="minutes"), "min_cell": MIN_CELL},
    "reports_by_year": rows("""
        SELECT vendor, year(collected_on) AS year, count(*) AS n
        FROM unified.report WHERE collected_on IS NOT NULL GROUP BY ALL ORDER BY ALL"""),
    "assays": rows("""
        SELECT vendor, assay_name, assay_class, count(*) AS n
        FROM unified.report GROUP BY ALL ORDER BY n DESC"""),
    "status": rows("""
        SELECT vendor, coalesce(report_status, '(none)') AS status, count(*) AS n
        FROM unified.report GROUP BY ALL ORDER BY vendor, n DESC"""),
    "disease": rows("""
        SELECT vendor, coalesce(disease_text, '(not stated)') AS disease,
               count(*) AS n, count(DISTINCT research_id) AS n_patients
        FROM unified.report GROUP BY vendor, disease
        QUALIFY row_number() OVER (PARTITION BY vendor ORDER BY n DESC) <= 25
        ORDER BY vendor, n DESC"""),
    # Denominators for gene frequencies: reports per vendor x disease, plus an all-disease rollup.
    "denom": rows("""
        SELECT vendor, coalesce(disease_text, '(not stated)') AS disease, count(*) AS n
        FROM unified.report GROUP BY GROUPING SETS ((vendor, disease), (vendor))"""),
    "gene_alt": rows(ALT + """,
        top AS (SELECT gene FROM alt WHERE alt_type <> 'VUS' GROUP BY gene ORDER BY count(DISTINCT report_id) DESC LIMIT 60)
        SELECT a.vendor, r.disease, a.gene, a.alt_type, count(DISTINCT a.report_id) AS n
        FROM alt a JOIN rep r USING (vendor, report_id)
        WHERE a.gene IN (SELECT gene FROM top)
        GROUP BY GROUPING SETS ((a.vendor, r.disease, a.gene, a.alt_type), (a.vendor, a.gene, a.alt_type))"""),
    "tmb_hist": rows("""
        SELECT vendor, least(floor(value / 2) * 2, 50) AS bin, count(*) AS n
        FROM unified.biomarker WHERE name = 'TMB' AND value IS NOT NULL GROUP BY ALL ORDER BY ALL"""),
    "biomarker_call": rows("""
        SELECT b.vendor, b.name, coalesce(r.disease_text, '(not stated)') AS disease, b.call_norm, count(*) AS n
        FROM unified.biomarker b JOIN unified.report r USING (vendor, report_id)
        WHERE b.name IN ('TMB', 'MSI')
        GROUP BY GROUPING SETS ((b.vendor, b.name, disease, b.call_norm), (b.vendor, b.name, b.call_norm))"""),
    "pdl1": rows("""
        SELECT unit, call, count(*) AS n FROM unified.biomarker WHERE name = 'PD-L1' GROUP BY ALL ORDER BY unit, n DESC"""),
    "loh_hist": rows("""
        SELECT least(floor(value / 5) * 5, 50) AS bin, count(*) AS n
        FROM unified.biomarker WHERE name = 'LOH' AND value IS NOT NULL GROUP BY ALL ORDER BY ALL"""),
    "vaf_hist": rows("""
        SELECT v.vendor, r.assay_class, floor(v.vaf * 20) / 20 AS bin, count(*) AS n
        FROM unified.variant v JOIN unified.report r USING (vendor, report_id)
        WHERE v.vaf BETWEEN 0 AND 1 AND NOT coalesce(v.is_vus, false)
        GROUP BY ALL ORDER BY ALL"""),
    "purity_hist": rows("""
        SELECT vendor, least(floor(tumor_purity_pct / 10) * 10, 90) AS bin, count(*) AS n
        FROM unified.report WHERE tumor_purity_pct IS NOT NULL GROUP BY ALL ORDER BY ALL"""),
    # Coverage: a gene "has evidence" on a report if it was called wild-type/pertinent-negative or altered.
    # Caris panel comes from its wild-type records; FMI panels aren't loaded, so assay_name stands in.
    "coverage": rows("""
        WITH caris_panel AS (SELECT report_id, min(panel) AS panel FROM unified.gene_tested WHERE vendor = 'caris' GROUP BY 1),
        panel AS (SELECT r.vendor, r.report_id, coalesce(cp.panel, r.assay_name) AS panel
                  FROM unified.report r LEFT JOIN caris_panel cp USING (report_id)),
        ev AS (
          SELECT vendor, report_id, gene FROM unified.gene_tested
          UNION ALL SELECT vendor, report_id, gene FROM unified.variant
          UNION ALL SELECT vendor, report_id, gene FROM unified.cna
        )
        SELECT p.vendor, p.panel, ev.gene, count(DISTINCT ev.report_id) AS n
        FROM ev JOIN panel p USING (vendor, report_id) WHERE ev.gene IS NOT NULL GROUP BY ALL"""),
    "panels": rows("""
        WITH caris_panel AS (SELECT report_id, min(panel) AS panel FROM unified.gene_tested WHERE vendor = 'caris' GROUP BY 1)
        SELECT r.vendor, coalesce(cp.panel, r.assay_name) AS panel, count(*) AS n
        FROM unified.report r LEFT JOIN caris_panel cp USING (report_id) GROUP BY ALL ORDER BY vendor, n DESC"""),
    "quality": rows("""
        SELECT 'reports without a collection date' AS item, count(*) AS n FROM unified.report WHERE collected_on IS NULL
        UNION ALL SELECT 'reports without a stated disease', count(*) FROM unified.report WHERE disease_text IS NULL
        UNION ALL SELECT 'FMI reports with unknown test type', count(*) FROM unified.report WHERE vendor = 'fmi' AND assay_name = 'undefined'
        UNION ALL SELECT 'FMI amendment records', count(*) FROM fmi.amendment
        UNION ALL SELECT 'Caris QNS (insufficient sample)', count(*) FROM unified.report WHERE vendor = 'caris' AND report_status = 'QNS'
        UNION ALL SELECT 'FMI QC fail', count(*) FROM unified.report WHERE vendor = 'fmi' AND report_status = 'Fail'
        UNION ALL SELECT 'variants missing VAF', count(*) FROM unified.variant WHERE vaf IS NULL"""),
}

# GROUPING SETS rollups arrive with disease = NULL; name them.
for key in ("denom", "gene_alt", "biomarker_call"):
    for r in summary[key]:
        r["disease"] = r["disease"] or "All diseases"

# Self-check: nothing below the small-cell floor and nothing row-level leaves this loader.
for key, val in summary.items():
    for r in val if isinstance(val, list) else [val]:
        assert r.get("n") is None or r["n"] >= MIN_CELL, (key, r)
        assert not {"report_id", "research_id"} & r.keys(), (key, r)

json.dump(summary, sys.stdout, default=str)
