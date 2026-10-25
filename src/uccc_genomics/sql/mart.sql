-- Cohort mart (dashboard/COHORT_DISCOVERY.md §3.2): tables, not views; the cohort compiler
-- reads them on every request. Built by deid.py from unified.* / vendor schemas after unified.sql.
-- Spec: docs/specs/33-mart-schema-mart-report-and-mart-fact.md.
CREATE SCHEMA IF NOT EXISTS mart;

-- One row per unified.report row: the population dimensions a cohort filters and pivots on.
-- collected_on (per-patient shifted by deid) only orders two reports of one patient (`sequence`); it is never output.
CREATE OR REPLACE TABLE mart.report AS
WITH age AS (
  -- Caris liquid specimens carry an age sentinel, so age is a tissue-only attribute (as cohort_api.REP).
  SELECT case_id, max(age_at_collection) AS age FROM caris.specimen WHERE specimen_kind = 'tumor' GROUP BY 1
),
-- ponytail: site/site_type come from the case's first tumor specimen only, so later specimens are
-- not represented; upgrade path is one `specimen` fact per specimen.
spec AS (
  SELECT * FROM caris.specimen WHERE specimen_kind = 'tumor'
  QUALIFY row_number() OVER (PARTITION BY case_id ORDER BY specimen_idx) = 1
),
-- RNA/cfTNA TPM files are transcriptome; gDNA files are DNA. wtsExpression percentiles also count.
wts AS (
  SELECT DISTINCT case_id FROM caris.gene_tpm WHERE assay IN ('RNA', 'cfTNA')
  UNION
  SELECT DISTINCT case_id FROM caris.wts_expression
),
base AS (
  SELECT r.research_id, r.vendor, r.report_id,
         year(r.collected_on)::INTEGER AS year, r.collected_year_complete AS year_complete, r.collected_on,
         lower(r.gender) AS sex,
         CASE WHEN r.vendor = 'caris' AND r.assay_class = 'tissue' THEN a.age::INTEGER END AS age,
         r.oncotree_code AS oncotree, r.organ_system AS organ, r.disease_text AS disease,
         r.assay_class, r.assay_name, r.tumor_purity_pct::DOUBLE AS purity,
         lower(trim(s.site_type)) AS site_type, lower(trim(s.site)) AS site,
         (r.vendor = 'caris' AND w.case_id IS NOT NULL) AS has_wts
  FROM unified.report r
  LEFT JOIN age a ON r.vendor = 'caris' AND a.case_id = r.report_id
  LEFT JOIN spec s ON r.vendor = 'caris' AND s.case_id = r.report_id
  LEFT JOIN wts w ON r.vendor = 'caris' AND w.case_id = r.report_id
)
SELECT research_id, vendor, report_id, year, year_complete, sex, age,
       CASE WHEN age IS NULL THEN 'unknown' WHEN age < 50 THEN '<50' WHEN age < 65 THEN '50-64'
            WHEN age < 75 THEN '65-74' ELSE '75+' END AS age_band,
       oncotree, organ, disease, assay_class, assay_name, purity, site_type, site, has_wts, collected_on
FROM base
ORDER BY vendor, report_id;

-- One row per finding; arms are UNION ALL BY NAME: every arm aliases the columns it fills and
-- the rest are NULL, so a swapped sub/val or key/sub can't load into the wrong column.
-- kind/key/sub/val/num/unit/tier mean different things per kind (README Schemas).
-- Gene-keyed arms drop NULL / 'N/A' / '' genes as cohort_api.ALT does. unit is NULL whenever num is.
CREATE OR REPLACE TABLE mart.fact AS
SELECT DISTINCT research_id, vendor, report_id, kind, key, sub, val, num::DOUBLE AS num,
       CASE WHEN num IS NOT NULL THEN unit END AS unit, tier
FROM (
  -- Every tier is kept, benign included; the compiler's tier[] default (pathogenic,
  -- likely_pathogenic) is what keeps benign out of a count. A tier filter applies to sub = 'mutation' only.
  SELECT research_id, vendor, report_id, 'alteration' AS kind, gene AS key, 'mutation' AS sub,
         regexp_replace(hgvs_p, '^p\.', '') AS val, tier
  FROM unified.variant WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'alteration' AS kind, gene AS key, cn_type AS sub
  FROM unified.cna WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'alteration' AS kind, gene1 AS key, 'fusion' AS sub, gene2 AS val
  FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'alteration' AS kind, gene2 AS key, 'fusion' AS sub, gene1 AS val
  FROM unified.fusion WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'biomarker' AS kind, name AS key, call_norm AS val, value AS num,
         CASE name WHEN 'TMB' THEN 'mut/Mb' WHEN 'LOH' THEN '%' END AS unit
  FROM unified.biomarker WHERE name IN ('TMB', 'MSI', 'LOH')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'ihc' AS kind, name AS key, clone AS sub, call_norm AS val,
         value AS num, unit
  FROM unified.biomarker WHERE vendor = 'caris' AND name NOT IN ('TMB', 'MSI', 'LOH')
  UNION ALL BY NAME
  SELECT r.research_id, 'caris' AS vendor, r.case_id AS report_id, 'expression' AS kind, e.gene AS key,
         e.tpm_percentile AS num, 'percentile' AS unit
  FROM caris.wts_expression e JOIN caris.report r USING (case_id)
  WHERE e.tpm_percentile IS NOT NULL AND e.gene IS NOT NULL AND e.gene NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'tested_negative' AS kind, gene AS key, evidence AS sub
  FROM unified.gene_tested WHERE gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL BY NAME
  SELECT r.research_id, 'caris' AS vendor, r.case_id AS report_id, 'actionability' AS kind,
         'caris_level1' AS key, t.biomarker AS sub, lower(t.therapy) AS val
  FROM caris.therapy t JOIN caris.report r USING (case_id)
  WHERE lower(t.level) = 'level 1' AND lower(t.association) = 'benefit'
  UNION ALL BY NAME
  SELECT r.research_id, 'fmi' AS vendor, r.report_id, 'actionability' AS kind,
         'fmi_fda_any_indication' AS key, t.gene AS sub, lower(coalesce(t.generic_name, t.name)) AS val
  FROM fmi.therapy t JOIN fmi.report r USING (report_id)
  WHERE t.fda_approved AND lower(t.effect) = 'sensitizing' AND t.include IS NOT false
  UNION ALL BY NAME
  SELECT r.research_id, 'fmi' AS vendor, r.report_id, 'actionability' AS kind, 'fmi_trial' AS key,
         t.gene AS sub, t.nct_id AS val
  FROM fmi.trial t JOIN fmi.report r USING (report_id)
  WHERE t.nct_id IS NOT NULL AND t.include IS NOT false
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'specimen' AS kind, 'site_type' AS key, site_type AS val
  FROM mart.report WHERE site_type IS NOT NULL
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'specimen' AS kind, 'site' AS key, site AS val
  FROM mart.report WHERE site IS NOT NULL
  UNION ALL BY NAME
  SELECT research_id, vendor, report_id, 'specimen' AS kind, 'purity' AS key, purity AS num, '%' AS unit
  FROM mart.report WHERE purity IS NOT NULL
)
ORDER BY kind, key, research_id;
