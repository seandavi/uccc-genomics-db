-- Typed views over result.payload, one per Caris result kind.
-- Loaded by load.py after the tables are built; safe to re-run.

CREATE OR REPLACE VIEW caris.variant AS
SELECT case_id, test_idx, result_idx, biomarker_name, gene, result, result_group, genomic_source,
       payload->>'hgvsCodingChange'  AS hgvs_c,
       payload->>'hgvsProteinChange' AS hgvs_p,
       payload->>'chromosome'        AS chrom,
       payload->>'genomeBuild'       AS genome_build,
       try_cast(payload->>'exon' AS INT) AS exon,
       payload->>'molecularConsequence' AS consequence,
       payload->>'variantSource'     AS variant_source,
       payload->>'genotype'          AS genotype,
       try_cast(payload->'alleleFrequencyInformation'->>'alleleFrequency' AS DOUBLE) AS vaf_pct,
       try_cast(payload->'readInformation'->>'readDepth' AS INT)                     AS read_depth,
       try_cast(payload->>'plasmaVariantFrequency' AS DOUBLE) AS plasma_vaf_pct,
       try_cast(payload->>'buffyCoatFrequency'     AS DOUBLE) AS buffy_coat_vaf_pct,
       payload->'alterationDetails'->'transcriptAlterationDetails'->>'transcriptID'              AS transcript_id,
       try_cast(payload->'alterationDetails'->'transcriptAlterationDetails'->>'transcriptStartPosition' AS BIGINT) AS start_pos,
       try_cast(payload->'alterationDetails'->'transcriptAlterationDetails'->>'transcriptStopPosition'  AS BIGINT) AS stop_pos,
       payload->'alterationDetails'->'transcriptAlterationDetails'->>'referenceNucleotide' AS ref,
       payload->'alterationDetails'->'transcriptAlterationDetails'->>'observedNucleotide'  AS alt,
       payload->>'dbVarID' AS dbvar_id,
       (payload->>'unknownSignificance') = 'true' AS vus,
       (payload->>'wildtypeBiomarker') IS NOT NULL AS wildtype,
       payload->'labSpecific'->>'NGSPanelName' AS panel, payload->'labSpecific'->>'analysisPipelineVersion' AS pipeline_version,
       interpretation
FROM caris.result WHERE kind = 'genomicAlteration';

CREATE OR REPLACE VIEW caris.cna AS
SELECT case_id, test_idx, result_idx, biomarker_name, gene, result, result_group, genomic_source,
       payload->>'chromosome' AS chrom, payload->>'genomeBuild' AS genome_build,
       payload->>'genomicCoordinates' AS coordinates,
       payload->>'copyNumberType' AS cn_type,
       try_cast(payload->>'copyNumber'      AS DOUBLE) AS copy_number,
       try_cast(payload->>'copyNumberRatio' AS DOUBLE) AS cn_ratio,
       try_cast(payload->>'copyNumberCounted' AS DOUBLE) AS cn_counted,
       try_cast(payload->>'copyNumberControl' AS DOUBLE) AS cn_control,
       payload->>'threshold' AS threshold,
       payload->'labSpecific'->>'NGSPanelName' AS panel
FROM caris.result WHERE kind = 'copyNumberAlteration';

CREATE OR REPLACE VIEW caris.fusion AS
SELECT case_id, test_idx, result_idx, biomarker_name, gene, result, result_group, genomic_source,
       payload->>'gene1' AS gene1, payload->>'gene2' AS gene2,
       payload->>'exon1' AS exon1, payload->>'exon2' AS exon2,
       payload->>'transcriptID1' AS transcript1, payload->>'transcriptID2' AS transcript2,
       payload->>'fusionISOForm' AS isoform, payload->>'genomicBreakpoint' AS breakpoint,
       payload->>'genomeBuild' AS genome_build, payload->>'genotype' AS genotype, interpretation
FROM caris.result WHERE kind = 'translocation';

CREATE OR REPLACE VIEW caris.ihc AS
SELECT case_id, test_idx, result_idx, biomarker_name, gene, result, result_group,
       payload->>'expressionType' AS expression_type,
       (payload->>'isExpressed') = 'true' AS expressed,
       (payload->>'equivocal') = 'true'   AS equivocal,
       try_cast(payload->>'intensity'    AS INT)    AS intensity,
       try_cast(payload->>'stainPercent' AS DOUBLE) AS stain_pct,
       try_cast(payload->>'score'   AS DOUBLE) AS score,
       try_cast(payload->>'cpScore' AS DOUBLE) AS cps,
       try_cast(payload->>'tpScore' AS DOUBLE) AS tps,
       payload->>'tcResult' AS tc_result, try_cast(payload->>'tcStainPercent' AS DOUBLE) AS tc_stain_pct,
       payload->>'icResult' AS ic_result, try_cast(payload->>'icStainPercent' AS DOUBLE) AS ic_stain_pct,
       payload->>'threshold' AS threshold
FROM caris.result WHERE kind = 'expressionAlteration';

CREATE OR REPLACE VIEW caris.wts_expression AS
SELECT case_id, test_idx, result_idx, gene,
       try_cast(payload->>'tpm' AS DOUBLE) AS tpm,
       try_cast(payload->>'tpmPercentile' AS DOUBLE) AS tpm_percentile
FROM caris.result WHERE kind = 'wtsExpression';

CREATE OR REPLACE VIEW caris.tmb AS
SELECT case_id, test_idx, result_idx, result_group, genomic_source,
       payload->>'mutationBurdenCall' AS call,
       try_cast(regexp_extract(payload->>'mutationBurdenScore', '[0-9.]+') AS DOUBLE) AS score_per_mb,
       payload->'labSpecific'->>'NGSPanelName' AS panel, interpretation
FROM caris.result WHERE kind = 'tumorMutationBurden';

CREATE OR REPLACE VIEW caris.msi AS
SELECT case_id, test_idx, result_idx, result_group, genomic_source,
       payload->>'msiCall' AS call, payload->'labSpecific'->>'NGSPanelName' AS panel, interpretation
FROM caris.result WHERE kind = 'microsatelliteInstability';

CREATE OR REPLACE VIEW caris.loh AS
SELECT case_id, test_idx, result_idx, result, result_group, genomic_source,
       try_cast(payload->>'LOHpercentage' AS DOUBLE) AS loh_pct, interpretation
FROM caris.result WHERE kind = 'genomicLevelHeterozygosity';

CREATE OR REPLACE VIEW caris.therapy AS
SELECT case_id,
       t->>'biomarker' AS biomarker, t->>'method' AS method, t->>'analyte' AS analyte,
       t->>'result' AS result, t->>'therapyName' AS therapy, t->>'therapyAssociation' AS association,
       t->>'biomarkerLevel' AS level
FROM (SELECT case_id, unnest(json_extract(therapies, '$[*].therapyRecommendation[*]')) AS t
      FROM caris.report WHERE therapies IS NOT NULL);
