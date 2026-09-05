"""Framework data loader: cohort exploration and feasibility aggregates.

Small-cell rule: any cell count below MIN_CELL (5) is dropped before leaving the loader.
Zero row-level records: no dict contains report_id or research_id.
Dates are shifted per patient by up to ±6 months, so year granularity is used.
"""
import json
import sys

from uccc_genomics.config import DEID_DB, DEID_DB_KEY, connect

MIN_CELL = 5
con = connect(db=(DEID_DB, DEID_DB_KEY, "READ_ONLY"))


def rows(sql: str) -> list[dict]:
    """Execute SQL and return dict rows, dropping any small cell below MIN_CELL."""
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [
        r
        for r in out
        if (r.get("n") is None or r["n"] >= MIN_CELL)
        and (r.get("n_patients") is None or r["n_patients"] >= MIN_CELL)
    ]


# Meta counts
meta_raw = con.execute("""
    SELECT count(*) AS total_reports,
           count(DISTINCT research_id) AS total_patients
    FROM unified.report
""").fetchone()

meta = {
    "total_reports": meta_raw[0],
    "total_patients": meta_raw[1],
    "n_reports": meta_raw[0],
    "n_patients": meta_raw[1],
    "min_year": 2014,
    "max_year": 2026,
    "min_cell": MIN_CELL,
}

# Diseases with count >= MIN_CELL
diseases = rows("""
    SELECT coalesce(disease_text, '(not stated)') AS disease, count(*) AS n
    FROM unified.report
    GROUP BY 1
    HAVING n >= 5
    ORDER BY n DESC
""")

# Top genes with alteration count >= MIN_CELL (excluding 'N/A' and NULL)
genes = rows("""
    WITH alt AS (
      SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type
      FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene, cn_type FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene1, 'fusion' FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene2, 'fusion' FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
    )
    SELECT gene, count(DISTINCT report_id) AS n
    FROM alt
    GROUP BY gene
    HAVING n >= 5
    ORDER BY n DESC
""")

# Annual disease denoms: reports and patient counts by (year, disease, vendor, assay_class)
annual_disease_denoms = rows("""
    SELECT year(collected_on) AS year, coalesce(disease_text, '(not stated)') AS disease, vendor, assay_class,
           count(*) AS n, count(DISTINCT research_id) AS n_patients
    FROM unified.report
    WHERE collected_on IS NOT NULL AND year(collected_on) BETWEEN 2014 AND 2026
    GROUP BY 1, 2, 3, 4
    HAVING count(*) >= 5 AND count(DISTINCT research_id) >= 5
    ORDER BY 1, 2, 3, 4
""")

# Annual overall denoms: reports and patient counts by (year, vendor, assay_class)
annual_overall_denoms = rows("""
    SELECT year(collected_on) AS year, vendor, assay_class,
           count(*) AS n, count(DISTINCT research_id) AS n_patients
    FROM unified.report
    WHERE collected_on IS NOT NULL AND year(collected_on) BETWEEN 2014 AND 2026
    GROUP BY 1, 2, 3
    HAVING count(*) >= 5 AND count(DISTINCT research_id) >= 5
    ORDER BY 1, 2, 3
""")

# Annual disease gene alterations by (year, disease, vendor, gene, alt_type)
annual_disease_gene_alt = rows("""
    WITH alt AS (
      SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type
      FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene, cn_type FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene1, 'fusion' FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene2, 'fusion' FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
    ),
    rep AS (
      SELECT vendor, report_id, coalesce(disease_text, '(not stated)') AS disease, year(collected_on) AS year
      FROM unified.report
      WHERE collected_on IS NOT NULL AND year(collected_on) BETWEEN 2014 AND 2026
    )
    SELECT rep.year, rep.disease, a.vendor, a.gene, a.alt_type, count(DISTINCT a.report_id) AS n
    FROM alt a JOIN rep USING (vendor, report_id)
    GROUP BY rep.year, rep.disease, a.vendor, a.gene, a.alt_type
    HAVING count(DISTINCT a.report_id) >= 5
    ORDER BY rep.year, rep.disease, a.vendor, a.gene, a.alt_type
""")

# Annual overall gene alterations by (year, vendor, gene, alt_type)
annual_overall_gene_alt = rows("""
    WITH alt AS (
      SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type
      FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene, cn_type FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene1, 'fusion' FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene2, 'fusion' FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
    ),
    rep AS (
      SELECT vendor, report_id, year(collected_on) AS year
      FROM unified.report
      WHERE collected_on IS NOT NULL AND year(collected_on) BETWEEN 2014 AND 2026
    )
    SELECT rep.year, a.vendor, a.gene, a.alt_type, count(DISTINCT a.report_id) AS n
    FROM alt a JOIN rep USING (vendor, report_id)
    GROUP BY rep.year, a.vendor, a.gene, a.alt_type
    HAVING count(DISTINCT a.report_id) >= 5
    ORDER BY rep.year, a.vendor, a.gene, a.alt_type
""")

# Disease gene totals by (disease, vendor, gene, alt_type)
disease_gene_totals = rows("""
    WITH alt AS (
      SELECT vendor, report_id, gene, CASE WHEN coalesce(is_vus, false) THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type
      FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene, cn_type FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene1, 'fusion' FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
      UNION ALL SELECT vendor, report_id, gene2, 'fusion' FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
    ),
    rep AS (
      SELECT vendor, report_id, coalesce(disease_text, '(not stated)') AS disease
      FROM unified.report
    )
    SELECT rep.disease, a.vendor, a.gene, a.alt_type, count(DISTINCT a.report_id) AS n
    FROM alt a JOIN rep USING (vendor, report_id)
    GROUP BY rep.disease, a.vendor, a.gene, a.alt_type
    HAVING count(DISTINCT a.report_id) >= 5
    ORDER BY rep.disease, a.vendor, a.gene, a.alt_type
""")

# Top co-mutations for top 80 altered genes
top_comutations = rows("""
    WITH alt AS (
      SELECT report_id, gene
      FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '') AND NOT coalesce(is_vus, false)
      UNION SELECT report_id, gene FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
      UNION SELECT report_id, gene1 FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
      UNION SELECT report_id, gene2 FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 NOT IN ('N/A', '')
    ),
    top80 AS (
      SELECT gene
      FROM alt
      GROUP BY gene
      ORDER BY count(DISTINCT report_id) DESC
      LIMIT 80
    ),
    alt_top AS (
      SELECT DISTINCT report_id, gene
      FROM alt
      WHERE gene IN (SELECT gene FROM top80)
    )
    SELECT a1.gene AS gene_a, a2.gene AS gene_b, count(DISTINCT a1.report_id) AS n
    FROM alt_top a1
    JOIN alt_top a2 ON a1.report_id = a2.report_id AND a1.gene <> a2.gene
    GROUP BY 1, 2
    HAVING count(DISTINCT a1.report_id) >= 5
    ORDER BY 1, n DESC
""")

# Assays breakdown
assays = rows("""
    SELECT vendor, assay_name, assay_class, count(*) AS n
    FROM unified.report
    GROUP BY ALL
    HAVING count(*) >= 5
    ORDER BY n DESC
""")

cohort_data = {
    "meta": meta,
    "diseases": diseases,
    "genes": genes,
    "annual_disease_denoms": annual_disease_denoms,
    "annual_overall_denoms": annual_overall_denoms,
    "annual_disease_gene_alt": annual_disease_gene_alt,
    "annual_overall_gene_alt": annual_overall_gene_alt,
    "disease_gene_totals": disease_gene_totals,
    "top_comutations": top_comutations,
    "assays": assays,
}

# Strict privacy and small-cell governance assertions
for section_name, section_val in cohort_data.items():
    rows_to_check = section_val if isinstance(section_val, list) else [section_val]
    for row in rows_to_check:
        assert not ({"report_id", "research_id"} & row.keys()), (
            f"Governance violation: row-level ID in {section_name}: {row}"
        )
        for col, val in row.items():
            if col in ("n", "n_patients") and isinstance(val, int):
                assert val >= MIN_CELL, (
                    f"Governance violation: cell count < {MIN_CELL} in {section_name}.{col}: {row}"
                )

json.dump(cohort_data, sys.stdout, default=str)
