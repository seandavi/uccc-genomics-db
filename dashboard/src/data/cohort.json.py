"""Framework data loader: cohort and accrual-volume aggregates.

Small-cell rule: any count below MIN_CELL is dropped here, before it leaves the loader.
Nothing row-level is emitted. Dates in the de-id file are already shifted per patient.

Design note: year x disease x gene cells are sparse (only ~25% of alteration records
survive the floor at that grain), so the page's headline numbers come from the all-years
sections and the annual sections carry only denominators plus what survives.
"""
import json
import sys

from uccc_genomics.config import DEID_DB, DEID_DB_KEY, connect

MIN_CELL = 5
con = connect(db=(DEID_DB, DEID_DB_KEY, "READ_ONLY"))


def rows(sql: str) -> list[dict]:
    """Rows as dicts, minus any whose `n` or `n_patients` is a small cell."""
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [r for r in out if all(r.get(k) is None or r[k] >= MIN_CELL for k in ("n", "n_patients"))]


# One row per (report, gene, alteration type); `vus` folds the type into the toggle the page needs.
ALT = """
WITH alt AS (
  SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type,
         coalesce(is_vus, false) AS vus
  FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene, cn_type, false FROM unified.cna
    WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene1, 'fusion', false FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene2, 'fusion', false FROM unified.fusion
    WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
),
rep AS (
  SELECT vendor, report_id, research_id, disease_text AS disease, assay_class, year(collected_on) AS year
  FROM unified.report
)
"""

cohort = {
    "meta": rows("""
        SELECT count(*) AS n_reports, count(DISTINCT research_id) AS n_patients,
               min(year(collected_on)) AS min_year, max(year(collected_on)) AS max_year
        FROM unified.report""")[0] | {"min_cell": MIN_CELL},
    # Pickers, most frequent first.
    "diseases": rows("SELECT disease_text AS disease, count(*) AS n FROM unified.report GROUP BY 1 ORDER BY n DESC"),
    "genes": rows(ALT + "SELECT gene, count(DISTINCT report_id) AS n FROM alt WHERE NOT vus GROUP BY 1 ORDER BY n DESC"),
    # Tested reports, all years. disease = NULL rows are the all-disease rollup.
    "denoms": rows("""
        SELECT disease_text AS disease, vendor, count(*) AS n, count(DISTINCT research_id) AS n_patients
        FROM unified.report GROUP BY GROUPING SETS ((disease, vendor), (vendor))"""),
    # Tested reports per year, for the trend and the accrual window.
    "annual_denoms": rows("""
        SELECT year(collected_on) AS year, disease_text AS disease, vendor, assay_class,
               count(*) AS n, count(DISTINCT research_id) AS n_patients
        FROM unified.report WHERE collected_on IS NOT NULL
        GROUP BY GROUPING SETS ((year, disease, vendor, assay_class), (year, vendor, assay_class))"""),
    # Reports with >= 1 alteration in the gene, all years: the headline count and prevalence.
    "gene_totals": rows(ALT + """
        SELECT r.disease, a.vendor, a.gene, a.vus, count(DISTINCT a.report_id) AS n
        FROM alt a JOIN rep r USING (vendor, report_id)
        GROUP BY GROUPING SETS ((r.disease, a.vendor, a.gene, a.vus), (a.vendor, a.gene, a.vus))"""),
    # Same, split by alteration class, for the class-breakdown chart.
    "gene_alt_types": rows(ALT + """
        SELECT r.disease, a.vendor, a.gene, a.alt_type, count(DISTINCT a.report_id) AS n
        FROM alt a JOIN rep r USING (vendor, report_id)
        GROUP BY GROUPING SETS ((r.disease, a.vendor, a.gene, a.alt_type), (a.vendor, a.gene, a.alt_type))"""),
    # Per-year alteration counts: sparse after suppression, shown as "observed" only.
    "annual_gene": rows(ALT + """
        SELECT r.year, r.disease, a.vendor, a.gene, a.vus, count(DISTINCT a.report_id) AS n
        FROM alt a JOIN rep r USING (vendor, report_id) WHERE r.year IS NOT NULL
        GROUP BY GROUPING SETS ((r.year, r.disease, a.vendor, a.gene, a.vus), (r.year, a.vendor, a.gene, a.vus))"""),
    # Pairwise co-alteration among the 80 most-altered genes, all diseases (per-disease pairs are too sparse).
    "top_comutations": rows(ALT + """,
        g AS (SELECT DISTINCT report_id, gene FROM alt WHERE NOT vus),
        top AS (SELECT gene FROM g GROUP BY gene ORDER BY count(*) DESC LIMIT 80)
        SELECT a.gene AS gene_a, b.gene AS gene_b, count(*) AS n
        FROM g a JOIN g b ON a.report_id = b.report_id AND a.gene <> b.gene
        WHERE a.gene IN (SELECT gene FROM top) AND b.gene IN (SELECT gene FROM top)
        GROUP BY 1, 2 ORDER BY 1, n DESC"""),
}

# GROUPING SETS rollups arrive with disease = NULL; name them.
for key in ("denoms", "annual_denoms", "gene_totals", "gene_alt_types", "annual_gene"):
    for r in cohort[key]:
        r["disease"] = r["disease"] or "All diseases"

# Self-check: nothing below the small-cell floor and nothing row-level leaves this loader.
for key, val in cohort.items():
    for r in val if isinstance(val, list) else [val]:
        assert not {"report_id", "research_id"} & r.keys(), (key, r)
        for k in ("n", "n_patients"):
            assert r.get(k) is None or r[k] >= MIN_CELL, (key, r)

json.dump(cohort, sys.stdout, default=str)
