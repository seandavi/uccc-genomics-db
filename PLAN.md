# Plan: unified UCCC vendor-genomics database (Caris + Foundation Medicine)

Status: **built 2026-09-04** (steps 1–4 below; README is the operating doc). Kept for the reasoning
and the column-level vendor mapping. Deviations from the proposal as written: FMI's `Genes` block
turned out to be reported alterations, not the panel, so `gene_tested` uses FMI pertinent negatives
only; FMI leaves MRN empty on ~20% of reports, so patient identity falls back to name+DOB;
scheduling uses the platform's systemd `--user` timer + ntfy rather than cron.

## What exists today

| | Caris | Foundation Medicine (FMI) |
|---|---|---|
| Source | S3 bucket, one prefix per case; JSON + XML + PDF + VCF + TPM CSV | institutional CIFS share mounted on the FMI host (`FMI_SRC`); XML + PDF, one file per report |
| Volume | 2,345 cases, 2,093 patients, 2018–2026 | 3,544 XML, 3,428 parse, 2,602 patients, collections 2005–2026 |
| Assays | 600-gene panel (hg19, pre-2024); exome+WTS (hg38); liquid cfTNA (hg38) | FoundationOne, F1CDx, F1CDx+RNA, F1 Liquid CDx, FoundationACT, HemeComplete, HemeOnc (all hg19) |
| Code | `caris-db` (this repo): `load.py`, `views.sql`, `deid.py` → two DuckDB files | `seandavi/foundation-medicine-xml-parser` (public; run daily by cron on the FMI host) → 5 CSV + 1 xlsx. `seandavi/fmi_temporal_workflow` (private) wraps the same parser in Temporal; superseded by the cron, not running. |
| PHI handling | split at load: `caris_phi.duckdb` vs `caris.duckdb` | none in the legacy parser output; this repo splits FMI at load the same way |
| Patient overlap | 51 patients have both a Caris and an FMI report | |

FMI parser findings worth fixing regardless of this plan:
- **116 XML files are silently dropped** on the FMI host by an uncommitted `except: pass` in `generate_report_frames`. The committed repo raises instead. Either way the daily CSVs undercount. They are: 80 **FoundationOne Monitor** reports (ctDNA monitoring assay; no `ReportId` element, so `get_report_id` fails — a distinct assay with its own result shape, worth its own table) and 36 files with no `variant-report` block at all (likely QNS / no-result reports; still carry PMI and should land as report rows with zero results, as Caris QNS cases do).
- The parser reads `short-variant`, `copy-number-alteration`, `rearrangement`, `biomarkers` (MSI, TMB), and PMI. It ignores: `Genes/Gene/Include` (the curated alteration list with `Therapies`, `Trials`, `References`, and interpretation text), `PertinentNegatives`, `VariantProperties` (isVUS per variant), `AlterationProperties` (dnaFraction, isSubclonal), `subclonal` on short variants, `quality-control`, `samples/sample` (bait-set, mean-exon-depth, nucleic-acid-type), `variant-report` attrs `percent-tumor-nuclei`, `tissue-of-origin`, `pipeline-version`, `priorTests`, `Amendmends`, `non-human-content`, `processSites`. The VUS flag and pertinent negatives are the ones a unified variant table needs.

## Target shape

One repo, one loader per vendor, one de-id step, one DuckDB pair. Same PHI split as today.

```
uccc-genomics-db/                      (rename of caris-db)
  vendors/caris/   load.py views.sql   -> schema caris.*   (tables as today)
  vendors/fmi/     load.py views.sql   -> schema fmi.*     (report, specimen, sample, short_variant, cna,
                                                            rearrangement, biomarker, gene_tested,
                                                            alteration (curated Include block), therapy, trial)
  unified.sql                          -> schema unified.* views/tables over caris.* + fmi.*
  deid.py                              -> genomics.duckdb from genomics_phi.duckdb, all three schemas
```

DuckDB schemas keep vendor tables and unified tables in the same file without name collisions. The unified layer is *views first*; materialize only if a query is slow.

### Unified tables (only where both vendors genuinely carry the concept)

| unified | grain | Caris source | FMI source | notes |
|---|---|---|---|---|
| `patient` | research_id | report.mrn | assay_and_patient_data.mrn | one keyed hash across vendors; MRN normalized to digits first (FMI parser already does this; Caris loader must match) |
| `report` | vendor + report_id | report + specimen | PMI + variant-report | columns: vendor, report_id, research_id, assay_name, assay_class (tissue/liquid/heme), genome_build, ordered/collected/received (shifted), disease_text (vendor's), primary_site_text, tumor_purity (Caris: histopathology.hePercentTumorNuclei; FMI: purity-assessment / percent-tumor-nuclei) |
| `variant` | report + gene + hgvs | variant view (non-wildtype) | short_variant | gene, hgvs_c, hgvs_p, chrom, pos, ref/alt (Caris only), vaf (Caris `vaf_pct`/100; FMI `allele-fraction`), depth, consequence (Caris molecularConsequence; FMI functional-effect), is_vus (Caris unknownSignificance; FMI VariantProperties.isVUS — **not parsed today**), is_subclonal (FMI only), genome_build, transcript |
| `cna` | report + gene | cna view | copy_number_alteration | gene, cn_type (Amplified/Deleted vs amplification/loss → normalized), copy_number, ratio, coordinates/position, equivocal (FMI) |
| `fusion` | report + gene pair | fusion view | rearrangement | gene1/gene2 (FMI: targeted-gene/other-gene), breakpoints, description, supporting_reads (FMI), is_known (FMI status) |
| `biomarker` | report + name | tmb, msi, loh views | biomarkers (MSI, TMB, LOH when present) | long table: name ∈ {TMB, MSI, LOH, PD-L1(IHC, Caris only)}, call, value, unit. Do not force PD-L1 into the same row shape as TMB beyond (name, call, value, unit). |
| `gene_tested` | report + gene | variant.wildtype rows + panel from labSpecific | `Genes/Gene/Name` list + `PertinentNegatives` — **not parsed today** | needed so "no KRAS mutation" is distinguishable from "KRAS not on panel". Highest-value addition for cohort work. |

Stays vendor-only (no unified table): Caris `wts_expression`, `gene_tpm`, `ihc` beyond PD-L1, `histopathology`, pharmacogenomics, pathogen reads; FMI `therapy`/`trial` links, `quality-control`, `priorTests`, `Amendmends`. Query them under `caris.*` / `fmi.*`.

### De-identification, unified
- Same `deid.py` pattern: keyed hash for research_id (from normalized MRN) and for each vendor's report_id; one date shift per patient applied to every date in every schema. One key file.
- FMI has *more* free-text PHI surface than Caris: `pathologist_comment`, `pathology_diagnosis`, `submitted_diagnosis`, `Interpretation` text, `CopiedPhysician1`. Drop the comment; keep vendor diagnosis strings only after a scan for names/dates (same regex asserts as today, extended with an NPI/8+digit check).
- FMI report IDs (`ORD-…`, `TRF…`, `CRF…`, `QRF…`) appear inside `specimen`, `sample`, and `SampleName` attrs and in the `Include` text; hash or drop those fields too, and keep the "no TN/ORD/TRF/CRF/QRF token survives" assert.

## Sequencing

1. **FMI loader (vendor table only, no unified yet).** Port `foundation-medicine-xml-parser` logic into `vendors/fmi/load.py` writing straight to DuckDB (skip polars/xlsx). Add the missing blocks: `Genes/Include` (curated alterations + VUS), `PertinentNegatives`, `samples`, `variant-report` extras, `AlterationProperties`. Fail loudly per file, log the 116 rejects to a table instead of `pass`. Input: the XML directory on the FMI host — so the loader runs there, or the XMLs get mirrored to the pipeline host `$DATA/raw/fmi/` (3.5k small files; `rsync` over ssh, same "raw mirror is the backstop" pattern as Caris). Recommend the mirror: one host holds both PHI stores, one place to secure.
2. **Rename + restructure** `caris-db` → `uccc-genomics-db` with `vendors/caris/`, `vendors/fmi/`; schemas `caris`, `fmi` in one `genomics_phi.duckdb`. Loader for each vendor is independent; `deid.py` handles both.
3. **Unified views** in `unified.sql`, in this order: `patient`, `report`, `variant`, `cna`, `fusion`, `biomarker`, then `gene_tested`. Each view is a `UNION ALL BY NAME` of two vendor SELECTs with a `vendor` column. Nothing materialized.
4. **Replace the FMI cron.** Once (1) is trusted, the daily job becomes `sync → load → deid` (see `SCHEDULING.md` for the systemd-timer + ntfy convention). The CSV/xlsx export can be regenerated *from the DuckDB* for whoever still consumes the legacy export — ideally the de-identified version. That's a consumer conversation, not a technical one.
5. Later, if wanted: OncoTree mapping of the two vendors' disease vocabularies (FMI has `disease-ontology`; Caris has lineage/subLineage) so cohorts can be defined once. Not needed for the tables above.

## Not planned
- Loading Caris XML/PDF/VCF, or FMI PDFs.
- Publishing to cdsci-lake / R2 (PHI; also the de-id file is still a limited dataset by DUA, keep it on campus).
- Temporal. The repo can be archived; cron/systemd covers the need.
