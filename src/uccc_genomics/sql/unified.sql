-- Cross-vendor views. Built on the de-identified file only (needs research_id).
-- Each view is a UNION ALL BY NAME of one SELECT per vendor; `vendor` says which.
CREATE SCHEMA IF NOT EXISTS unified;

CREATE OR REPLACE VIEW unified.report AS
SELECT 'caris' AS vendor, r.case_id AS report_id, r.research_id,
       'Caris ' || r.test_code AS assay_name,
       CASE WHEN s.specimen_kind = 'liquidBiopsy' THEN 'liquid' ELSE 'tissue' END AS assay_class,
       (SELECT max(genome_build) FROM caris.variant v WHERE v.case_id = r.case_id) AS genome_build,
       r.ordered_at::DATE AS ordered_on, s.collected_on, r.received_at::DATE AS received_on, r.approved_at::DATE AS reported_on,
       r.gender, r.lineage AS disease_text, r.sub_lineage AS disease_detail_text, r.primary_site AS primary_site_text,
       r.icd_code,
       (SELECT try_cast(payload->>'hePercentTumorNuclei' AS DOUBLE) FROM caris.result x
         WHERE x.case_id = r.case_id AND x.kind = 'histopathology' LIMIT 1) AS tumor_purity_pct,
       r.report_type AS report_status
FROM caris.report r
LEFT JOIN (SELECT * FROM caris.specimen QUALIFY row_number() OVER (PARTITION BY case_id ORDER BY specimen_kind, specimen_idx) = 1) s
       ON s.case_id = r.case_id
UNION ALL BY NAME
SELECT 'fmi' AS vendor, r.report_id, r.research_id,
       r.test_type AS assay_name,
       CASE WHEN r.test_type ILIKE '%liquid%' OR r.test_type IN ('FoundationACT', 'FoundationOneMonitor') THEN 'liquid'
            WHEN r.test_type ILIKE '%heme%' THEN 'heme' ELSE 'tissue' END AS assay_class,
       'GRCh37/hg19' AS genome_build,
       NULL::DATE AS ordered_on, r.collected_on, r.received_on, NULL::DATE AS reported_on,
       r.gender, r.disease AS disease_text, r.pathology_diagnosis AS disease_detail_text, r.tissue_of_origin AS primary_site_text,
       NULL::VARCHAR AS icd_code,
       coalesce(r.purity_estimate, r.percent_tumor_nuclei) AS tumor_purity_pct,
       r.qc_status AS report_status
FROM fmi.report r;

CREATE OR REPLACE VIEW unified.patient AS
SELECT research_id, min(gender) AS gender, count(*) AS n_reports,
       count(DISTINCT vendor) AS n_vendors, list(DISTINCT vendor ORDER BY vendor) AS vendors,
       min(collected_on) AS first_collected_on, max(collected_on) AS last_collected_on
FROM unified.report GROUP BY research_id;

CREATE OR REPLACE VIEW unified.variant AS
SELECT 'caris' AS vendor, v.case_id AS report_id, r.research_id, v.gene, v.hgvs_c, v.hgvs_p,
       v.chrom, v.start_pos AS pos, v.ref, v.alt, v.transcript_id AS transcript,
       coalesce(v.vaf_pct, v.plasma_vaf_pct) / 100 AS vaf, v.read_depth AS depth,
       v.consequence, (v.vus OR v.result ILIKE '%uncertain significance%' OR v.result ILIKE '%unknown significance%') AS is_vus, NULL::BOOLEAN AS is_subclonal, v.genome_build, v.result AS vendor_call
FROM caris.variant v JOIN caris.report r USING (case_id)
WHERE NOT v.wildtype AND (v.hgvs_c IS NOT NULL OR v.hgvs_p IS NOT NULL)
UNION ALL BY NAME
SELECT 'fmi' AS vendor, v.report_id, r.research_id, v.gene, v.cds_effect AS hgvs_c, v.protein_effect AS hgvs_p,
       split_part(v.position, ':', 1) AS chrom, try_cast(split_part(v.position, ':', 2) AS BIGINT) AS pos,
       NULL::VARCHAR AS ref, NULL::VARCHAR AS alt, v.transcript,
       v.allele_fraction AS vaf, v.depth, v.functional_effect AS consequence,
       v.is_vus, v.subclonal AS is_subclonal, 'GRCh37/hg19' AS genome_build, v.status AS vendor_call
FROM fmi.short_variant v JOIN fmi.report r USING (report_id);

CREATE OR REPLACE VIEW unified.cna AS
SELECT 'caris' AS vendor, c.case_id AS report_id, r.research_id, c.gene,
       CASE WHEN c.cn_type ILIKE 'amplif%' THEN 'amplification' WHEN c.cn_type ILIKE 'delet%' OR c.cn_type ILIKE 'loss%' THEN 'loss'
            ELSE lower(c.cn_type) END AS cn_type,
       c.copy_number, c.cn_ratio AS ratio, c.coordinates, NULL::BOOLEAN AS equivocal, c.genome_build, c.result AS vendor_call
FROM caris.cna c JOIN caris.report r USING (case_id) WHERE c.cn_type IS NOT NULL
UNION ALL BY NAME
SELECT 'fmi' AS vendor, c.report_id, r.research_id, c.gene,
       CASE WHEN c.type ILIKE 'amplif%' THEN 'amplification' WHEN c.type ILIKE 'loss%' OR c.type ILIKE 'delet%' THEN 'loss'
            ELSE lower(c.type) END AS cn_type,
       c.copy_number, c.ratio, c.position AS coordinates, c.equivocal, 'GRCh37/hg19' AS genome_build, c.status AS vendor_call
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
       CASE WHEN i.tps IS NOT NULL THEN 'TPS' WHEN i.cps IS NOT NULL THEN 'CPS' ELSE '% stained' END AS unit
FROM caris.ihc i JOIN caris.report r USING (case_id) WHERE i.biomarker_name ILIKE 'PD-L1%'
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
