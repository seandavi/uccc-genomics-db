-- Cross-vendor views. Built on the de-identified file only (needs research_id).
-- Each view is a UNION ALL BY NAME of one SELECT per vendor; `vendor` says which.
CREATE SCHEMA IF NOT EXISTS unified;

CREATE OR REPLACE VIEW unified.report AS
SELECT *,
       -- deid.py shifts every date by up to ±182 days per patient (shift_days), so shifted year Y can
       -- still gain reports until real collections through Dec 31 of Y + 182 days have happened.
       make_date(year(collected_on), 12, 31) + 182 < current_date AS collected_year_complete
FROM (
SELECT 'caris' AS vendor, r.case_id AS report_id, r.research_id,
       'Caris ' || r.test_code AS assay_name,
       CASE WHEN s.specimen_kind = 'liquidBiopsy' THEN 'liquid' ELSE 'tissue' END AS assay_class,
       (SELECT max(genome_build) FROM caris.variant v WHERE v.case_id = r.case_id) AS genome_build,
       r.ordered_at::DATE AS ordered_on, s.collected_on, r.received_at::DATE AS received_on, r.approved_at::DATE AS reported_on,
       r.gender,
       -- Harmonized OncoTree & NCIt ontology terms
       coalesce(c.oncotree_code, 'OTHER') AS oncotree_code,
       coalesce(c.oncotree_name, r.lineage, 'Other') AS oncotree_name,
       coalesce(c.organ_system, 'Other') AS organ_system,
       c.ncit_code AS ncit_code,
       -- Standardized disease name (harmonized across vendors)
       coalesce(c.oncotree_name, r.lineage, '(not stated)') AS disease_text,
       r.sub_lineage AS disease_detail_text,
       r.primary_site AS primary_site_text,
       -- Raw provenance
       r.lineage AS raw_disease_text,
       r.sub_lineage AS raw_disease_detail,
       r.primary_site AS raw_primary_site,
       r.icd_code AS raw_icd_code,
       r.icd_code,
       (SELECT try_cast(payload->>'hePercentTumorNuclei' AS DOUBLE) FROM caris.result x
         WHERE x.case_id = r.case_id AND x.kind = 'histopathology' LIMIT 1) AS tumor_purity_pct,
       r.report_type AS report_status
FROM caris.report r
LEFT JOIN (SELECT * FROM caris.specimen QUALIFY row_number() OVER (PARTITION BY case_id ORDER BY specimen_kind, specimen_idx) = 1) s
       ON s.case_id = r.case_id
LEFT JOIN (SELECT * FROM reference.disease_crosswalk WHERE vendor = 'caris') c
       ON lower(trim(r.lineage)) = lower(trim(c.vendor_term))
UNION ALL BY NAME
SELECT 'fmi' AS vendor, r.report_id, r.research_id,
       r.test_type AS assay_name,
       CASE WHEN r.test_type ILIKE '%liquid%' OR r.test_type IN ('FoundationACT', 'FoundationOneMonitor') THEN 'liquid'
            WHEN r.test_type ILIKE '%heme%' THEN 'heme' ELSE 'tissue' END AS assay_class,
       'GRCh37/hg19' AS genome_build,
       NULL::DATE AS ordered_on, r.collected_on, r.received_on, NULL::DATE AS reported_on,
       r.gender,
       -- Harmonized OncoTree & NCIt ontology terms
       coalesce(co.oncotree_code, cd.oncotree_code, 'OTHER') AS oncotree_code,
       coalesce(co.oncotree_name, cd.oncotree_name, r.disease_ontology, r.disease, 'Other') AS oncotree_name,
       coalesce(co.organ_system, cd.organ_system, 'Other') AS organ_system,
       coalesce(co.ncit_code, cd.ncit_code) AS ncit_code,
       -- Standardized disease name (harmonized across vendors)
       coalesce(co.oncotree_name, cd.oncotree_name, r.disease_ontology, r.disease, '(not stated)') AS disease_text,
       r.pathology_diagnosis AS disease_detail_text,
       r.tissue_of_origin AS primary_site_text,
       -- Raw provenance
       r.disease AS raw_disease_text,
       r.disease_ontology AS raw_disease_detail,
       r.tissue_of_origin AS raw_primary_site,
       NULL::VARCHAR AS raw_icd_code,
       NULL::VARCHAR AS icd_code,
       coalesce(r.purity_estimate, r.percent_tumor_nuclei) AS tumor_purity_pct,
       r.qc_status AS report_status
FROM fmi.report r
LEFT JOIN (SELECT * FROM reference.disease_crosswalk WHERE vendor = 'fmi' AND vendor_field = 'disease_ontology') co
       ON lower(trim(r.disease_ontology)) = lower(trim(co.vendor_term))
LEFT JOIN (SELECT * FROM reference.disease_crosswalk WHERE vendor = 'fmi' AND vendor_field = 'disease') cd
       ON lower(trim(r.disease)) = lower(trim(cd.vendor_term))
);

CREATE OR REPLACE VIEW unified.patient AS
SELECT research_id, min(gender) AS gender, count(*) AS n_reports,
       count(DISTINCT vendor) AS n_vendors, list(DISTINCT vendor ORDER BY vendor) AS vendors,
       min(collected_on) AS first_collected_on, max(collected_on) AS last_collected_on
FROM unified.report GROUP BY research_id;

-- `tier` is what every filter uses; `is_vus` and `vendor_call` are kept as the vendor's own flags.
-- Vendor value -> tier mapping: docs/specs/32-data-readiness-significance-tier-her2.md and
-- docs/specs/76-older-fmi-reports-variants-only-in-genes.md.
CREATE OR REPLACE VIEW unified.variant AS
SELECT 'caris' AS vendor, v.case_id AS report_id, r.research_id, v.gene, v.hgvs_c, v.hgvs_p,
       v.chrom, v.start_pos AS pos, v.ref, v.alt, v.transcript_id AS transcript,
       coalesce(v.vaf_pct, v.plasma_vaf_pct) / 100 AS vaf, v.read_depth AS depth,
       lower(v.consequence) AS consequence, (v.vus OR v.result ILIKE '%uncertain significance%' OR v.result ILIKE '%unknown significance%') AS is_vus, NULL::BOOLEAN AS is_subclonal, v.genome_build, v.result AS vendor_call,
       NULL::VARCHAR AS source,
       CASE WHEN lower(v.result) IN ('pathogenic variant', 'mutated, pathogenic') THEN 'pathogenic'
            WHEN lower(v.result) IN ('likely pathogenic variant', 'mutated, presumed pathogenic') THEN 'likely_pathogenic'
            WHEN v.vus OR v.result ILIKE '%uncertain significance%' OR v.result ILIKE '%unknown significance%' THEN 'vus'
            WHEN lower(v.result) IN ('likely benign variant', 'benign variant', 'mutated, presumed benign') THEN 'likely_benign_or_benign'
            ELSE 'unclassified' END AS tier
FROM caris.variant v JOIN caris.report r USING (case_id)
WHERE NOT v.wildtype AND (v.hgvs_c IS NOT NULL OR v.hgvs_p IS NOT NULL)
UNION ALL BY NAME
SELECT 'fmi' AS vendor, v.report_id, r.research_id, v.gene, v.cds_effect AS hgvs_c, v.protein_effect AS hgvs_p,
       split_part(v.position, ':', 1) AS chrom, try_cast(split_part(v.position, ':', 2) AS BIGINT) AS pos,
       NULL::VARCHAR AS ref, NULL::VARCHAR AS alt, v.transcript,
       v.allele_fraction AS vaf, v.depth, lower(v.functional_effect) AS consequence,
       v.is_vus, v.subclonal AS is_subclonal, 'GRCh37/hg19' AS genome_build, v.status AS vendor_call, v.source,
       CASE WHEN v.is_vus THEN 'vus'
            WHEN lower(v.status) = 'known' THEN 'pathogenic'
            WHEN lower(v.status) = 'likely' THEN 'likely_pathogenic'
            -- Genes-block rows (#76) have no vendor status. On reports with both blocks every
            -- Genes-block short variant is known or likely, so they take the lower of the two.
            -- An inference, not a vendor call: docs/specs/76-older-fmi-reports-variants-only-in-genes.md.
            WHEN v.source = 'genes_block' THEN 'likely_pathogenic'
            ELSE 'unclassified' END AS tier
FROM fmi.short_variant v JOIN fmi.report r USING (report_id);

CREATE OR REPLACE VIEW unified.cna AS
SELECT 'caris' AS vendor, c.case_id AS report_id, r.research_id, c.gene,
       CASE WHEN c.cn_type ILIKE 'amplif%' THEN 'amplification' WHEN c.cn_type ILIKE 'delet%' OR c.cn_type ILIKE 'loss%' THEN 'loss'
            ELSE lower(c.cn_type) END AS cn_type,
       c.copy_number, c.cn_ratio AS ratio, c.coordinates, NULL::BOOLEAN AS equivocal, c.genome_build, c.result AS vendor_call, NULL::VARCHAR AS source
FROM caris.cna c JOIN caris.report r USING (case_id) WHERE c.cn_type IS NOT NULL
UNION ALL BY NAME
SELECT 'fmi' AS vendor, c.report_id, r.research_id, c.gene,
       CASE WHEN c.type ILIKE 'amplif%' THEN 'amplification' WHEN c.type ILIKE 'loss%' OR c.type ILIKE 'delet%' THEN 'loss'
            ELSE lower(c.type) END AS cn_type,
       c.copy_number, c.ratio, c.position AS coordinates, c.equivocal, 'GRCh37/hg19' AS genome_build, c.status AS vendor_call, c.source
FROM fmi.cna c JOIN fmi.report r USING (report_id);

CREATE OR REPLACE VIEW unified.fusion AS
SELECT 'caris' AS vendor, f.case_id AS report_id, r.research_id, f.gene1, f.gene2,
       f.isoform AS description, f.breakpoint AS breakpoint1, NULL::VARCHAR AS breakpoint2,
       NULL::INT AS supporting_reads, NULL::VARCHAR AS in_frame, f.genome_build, f.result AS vendor_call
FROM caris.fusion f JOIN caris.report r USING (case_id) WHERE f.gene2 IS NOT NULL
UNION ALL BY NAME
SELECT 'fmi' AS vendor, f.report_id, r.research_id, f.targeted_gene AS gene1, f.other_gene AS gene2,
       f.description, f.pos1 AS breakpoint1, f.pos2 AS breakpoint2,
       f.supporting_read_pairs AS supporting_reads, f.in_frame, 'GRCh37/hg19' AS genome_build, f.status AS vendor_call
FROM fmi.rearrangement f JOIN fmi.report r USING (report_id);

CREATE OR REPLACE VIEW unified.biomarker AS
SELECT *,
       -- vendor vocabularies differ (MSS/Stable, MSI-H/High, low/Low); `call` keeps the raw string
       CASE WHEN name = 'MSI' THEN
              CASE WHEN lower(call) IN ('mss', 'stable', 'msi-s') THEN 'stable'
                   WHEN lower(call) IN ('msi-h', 'high', 'msi-high') THEN 'high'
                   WHEN lower(call) IN ('msi-l', 'low') THEN 'low'
                   ELSE 'indeterminate' END
            WHEN name = 'TMB' THEN
              CASE WHEN lower(call) IN ('high', 'tmb-h') THEN 'high'
                   WHEN lower(call) = 'intermediate' THEN 'intermediate'
                   WHEN lower(call) IN ('low', 'tmb-l') THEN 'low' ELSE 'indeterminate' END
            -- Caris spells the same MMR and HER2 calls two ways; other IHC calls are kept as reported.
            -- HER2's breast scale (low/ultralow/null) is not folded into positive/negative; only
            -- spellings of the same result merge. The composite ER/PR/Her2/Neu marker is a different name.
            WHEN name = 'Mismatch Repair Status' THEN
              CASE WHEN lower(call) LIKE 'proficient%' THEN 'proficient'
                   WHEN lower(call) LIKE 'deficient%' THEN 'deficient' ELSE 'indeterminate' END
            WHEN name = 'ERBB2 (Her2/Neu)' THEN
              CASE WHEN lower(call) IN ('her2-positive', 'positive') THEN 'positive'
                   WHEN lower(call) IN ('her2-negative', 'negative') THEN 'negative'
                   WHEN lower(call) IN ('her2-low', 'low') THEN 'her2-low'
                   WHEN lower(call) = 'her2-ultralow' THEN 'her2-ultralow'
                   WHEN lower(call) = 'her2-null' THEN 'her2-null'
                   ELSE lower(call) END
            ELSE lower(call) END AS call_norm
FROM (
SELECT 'caris' AS vendor, t.case_id AS report_id, r.research_id, 'TMB' AS name, t.call, t.score_per_mb AS value, 'mut/Mb' AS unit
FROM caris.tmb t JOIN caris.report r USING (case_id)
UNION ALL BY NAME
SELECT 'caris' AS vendor, m.case_id AS report_id, r.research_id, 'MSI' AS name, m.call, NULL::DOUBLE AS value, NULL::VARCHAR AS unit
FROM caris.msi m JOIN caris.report r USING (case_id)
UNION ALL BY NAME
SELECT 'caris' AS vendor, l.case_id AS report_id, r.research_id, 'LOH' AS name, l.result AS call, l.loh_pct AS value, '%' AS unit
FROM caris.loh l JOIN caris.report r USING (case_id)
UNION ALL BY NAME
SELECT 'caris' AS vendor, i.case_id AS report_id, r.research_id, 'PD-L1' AS name, i.result AS call,
       coalesce(i.tps, i.cps, i.stain_pct) AS value,
       CASE WHEN i.tps IS NOT NULL THEN 'TPS' WHEN i.cps IS NOT NULL THEN 'CPS' ELSE '% stained' END AS unit,
       -- the clone is only in the vendor name, `PD-L1 (22c3)`; regexp_extract returns '' on no match
       lower(nullif(regexp_extract(i.biomarker_name, '\(([^)]+)\)', 1), '')) AS clone
FROM caris.ihc i JOIN caris.report r USING (case_id) WHERE i.biomarker_name ILIKE 'PD-L1%'
UNION ALL BY NAME
-- Every other Caris IHC marker (HER2, ER, PR, AR, MMR proteins, ALK, CLDN18, FOLR1 ...) under its own name.
-- FMI has no IHC; ERBB2 amplification in unified.cna is the nearest sequencing proxy, not the same measurement.
SELECT 'caris' AS vendor, i.case_id AS report_id, r.research_id, i.biomarker_name AS name, i.result AS call,
       i.stain_pct AS value, CASE WHEN i.stain_pct IS NOT NULL THEN '% stained' END AS unit
FROM caris.ihc i JOIN caris.report r USING (case_id) WHERE i.biomarker_name NOT ILIKE 'PD-L1%'
UNION ALL BY NAME
SELECT 'fmi' AS vendor, b.report_id, r.research_id,
       CASE b.name WHEN 'tumor-mutation-burden' THEN 'TMB' WHEN 'microsatellite-instability' THEN 'MSI'
                   WHEN 'loss-of-heterozygosity' THEN 'LOH' ELSE upper(b.name) END AS name,
       b.status AS call, b.score AS value, b.unit
FROM fmi.biomarker b JOIN fmi.report r USING (report_id)
);

-- "Tested and negative" evidence. Caris: every wild-type record; FMI: only the
-- pertinent-negative list (FMI panels are fixed per test_type; membership not loaded).
CREATE OR REPLACE VIEW unified.gene_tested AS
SELECT 'caris' AS vendor, v.case_id AS report_id, r.research_id, v.gene, 'wildtype' AS evidence, v.panel
FROM caris.variant v JOIN caris.report r USING (case_id) WHERE v.wildtype
UNION ALL BY NAME
SELECT 'fmi' AS vendor, p.report_id, r.research_id, p.gene, 'pertinent_negative' AS evidence, r.test_type AS panel
FROM fmi.pertinent_negative p JOIN fmi.report r USING (report_id);
