# Spec #33: mart schema — `mart.report` and `mart.fact` built by deid

Part of #23, phase 1 of `dashboard/COHORT_DISCOVERY.md` (§3.2, §4); `docs/ARCHITECTURE.md`
decision 3. Builds on #32 (tier, HER2 `call_norm`, lower-case consequence,
`collected_year_complete`). Label: `seam` (`sql/unified.sql`, `deid.py`, and the table every
future cohort count reads).

All examples are synthetic. Quoted vendor strings (`Level 1`, `Benefit`, `Sensitizing`,
`Primary`, `PD-L1 (22c3)`, gene TPM assay names `RNA`/`cfTNA`/`gDNA`) are vendor controlled
vocabulary, not patient data. No counts appear.

## Goal

`genomics deid` builds schema `mart` in `genomics.duckdb` with two **tables**:

- `mart.report`: one row per report (`unified.report` grain), with the population
  dimensions the cohort compiler filters and pivots on.
- `mart.fact`: one row per finding, in a long shape that every criterion kind of
  `COHORT_DISCOVERY.md` §3.1 (except `data` and `sequence`, below) compiles to with one
  `EXISTS` template.

## Non-goals

- No compiler, endpoint, page or MCP tool. Nothing reads `mart.*` yet; the cohort API and the
  dashboard loader keep their own SQL. No new output path, so no new suppression code.
- No change to id hashing, date shifting, PHI drop lists or the leak assert. `research_id` and
  `report_id` are read from the existing de-identified tables, never recomputed.
- No `data` kind rows (wts/liquid/tissue/both_vendors/serial). Those are phase 2 and derive
  from `mart.report` (`has_wts`, `assay_class`, `vendor`, `year`) at query time.
  No `sequence` kind rows either.
- No viral facts (`fmi.non_human`), which stay held (`COHORT_DISCOVERY.md` §1 issue 4).
- No Caris ISH rows (`unified.cna.cn_type` like `positive | ish group 1`), no CNA copy number,
  VAF or tiers on CNA/fusion rows. `§3.1` asks for none of these.
- No FMI specimen site. `fmi.report.specimen_site` exists, but §1 lists site and type as Caris
  only and FMI has no site type. That can be a follow-up.
- No full gene TPM matrix in the mart. `expression` holds Caris `wtsExpression` percentiles only.
- No ART indexes (`CREATE INDEX`). Insertion order plus DuckDB's automatic min/max zonemaps
  is enough for `kind`/`key` filters; ART indexes help point lookups and constraints, not
  these scans, and they slow the build.
- No MCP server schema-doc update (`server.py`'s reference text). The internal MCP `query` tool
  can read `mart.*` like every other de-id table.
- No new dependencies.

## Deviations from the issue and design docs (the implementer updates the docs in the same PR)

1. **`mart.fact` gains a `unit` column** (after `num`). §3.1's `ihc` criterion has
   `measure + at_least` (TPS vs CPS), and each Caris PD-L1 record carries exactly one of
   `tpScore`, `cpScore` or `stainPercent`. With `num` alone, `TPS ≥ 10` would match a record
   whose only score is CPS 12. `unit` says which measure `num` is, and it is NULL whenever
   `num` is NULL. Spellings reuse `unified.biomarker.unit` (`TPS`, `CPS`, `% stained`) plus
   `mut/Mb`, `%` and `percentile`. Update `COHORT_DISCOVERY.md` §3.2 (column list and
   examples).
2. **Expression rows have `sub = NULL`, `unit = 'percentile'`.** The §3.2 example puts
   `'percentile'` in `sub`, but with `unit` present that would say the same thing twice.
   Update the §3.2 example.
3. **`unified.biomarker` gains `clone`** (PD-L1 rows only). The view folds every
   `PD-L1 (…)` name to `PD-L1`, so the clone is lost before the mart can read it. The other
   option, reading `caris.ihc` directly in `mart.sql`, would duplicate the HER2/MMR
   `call_norm` CASE. This is an additive column, so `SELECT *` consumers only gain a column.
4. §3.2's `mart.report` list lacks `year_complete`. The issue has it, so add it to the doc.

## Design

### Files

| file | change |
|---|---|
| `src/uccc_genomics/sql/mart.sql` | **new**: builds `mart.report` then `mart.fact` |
| `src/uccc_genomics/sql/unified.sql` | `clone` column on the Caris PD-L1 branch of `unified.biomarker` |
| `src/uccc_genomics/deid.py` | run `mart.sql` after `unified.sql`; print the two row counts |
| `tests/test_pipeline.py` | fixture additions + one test per fact kind + report/shape tests |
| `README.md` | `mart.*` in the diagram, Layout `sql/` line, Schemas section; `clone` on `unified.biomarker` |
| `dashboard/COHORT_DISCOVERY.md` | §3.2 column lists/examples per deviations 1, 2, 4 |
| `AGENTS.md` | "schemas `caris.*`, `fmi.*`, `unified.*`" → add `mart.*`; Layout `sql/` line adds `mart.sql` |

`mart.sql` sits next to `unified.sql`; `config.sql("mart.sql")` loads it (package data under
`src/uccc_genomics/sql/` is already shipped, so no `pyproject.toml` change is needed).

### `deid.py`

Right after the existing `con.execute(sql("unified.sql"))` / `print("views: unified.*")`:

```python
con.execute(sql("mart.sql"))
for t in ("report", "fact"):
    print(f"mart.{t:12s} {con.execute(f'SELECT count(*) FROM mart.{t}').fetchone()[0]:>12,}")
```

Update the module docstring with one line saying it also builds `mart.*` from
`unified.*` (`sql/mart.sql`). Nothing else in `deid.py` changes. The leak assert keeps scanning
the vendor schemas only. Every text value in `mart.*` is copied from a column it already
scanned (or from `reference.disease_crosswalk`, which ships in the package), so the mart adds
no new text source.

### `unified.sql`: `unified.biomarker.clone`

In the Caris PD-L1 branch (`WHERE i.biomarker_name ILIKE 'PD-L1%'`) add:

```sql
lower(nullif(regexp_extract(i.biomarker_name, '\(([^)]+)\)', 1), '')) AS clone
```

`PD-L1 (22c3)` → `22c3`, `PD-L1 (SP142)` → `sp142`, plain `PD-L1` → NULL (checked on DuckDB
1.5.5: `regexp_extract` returns `''` on no match, hence `nullif`). Every other branch gets NULL
from `UNION ALL BY NAME`. Source: Caris JSON `expressionAlteration.biomarkerName`.

### `mart.sql`

```sql
-- Cohort mart (dashboard/COHORT_DISCOVERY.md §3.2): tables, not views; the cohort compiler
-- reads them on every request. Built by deid.py from unified.* / vendor schemas after unified.sql.
CREATE SCHEMA IF NOT EXISTS mart;
CREATE OR REPLACE TABLE mart.report AS ... ORDER BY vendor, report_id;
CREATE OR REPLACE TABLE mart.fact AS
SELECT DISTINCT research_id, vendor, report_id, kind, key, sub, val, num::DOUBLE AS num,
       CASE WHEN num IS NOT NULL THEN unit END AS unit, tier
FROM ( <arms below, UNION ALL BY NAME> )
ORDER BY kind, key, research_id;
```

Each arm aliases (`AS kind`, `AS key`, …) only the columns it fills; the rest come out NULL, and
a column is matched by name, so a swapped `sub`/`val` cannot load into the wrong column. New arms
follow the same pattern. The outer `SELECT` casts `num` to DOUBLE and nulls `unit` whenever `num`
is NULL (a Caris PD-L1 record with no score arrives as `value` NULL, `unit` `'% stained'`).

DuckDB preserves insertion order in `CREATE TABLE AS … ORDER BY`. Sorting on `kind, key` keeps
each kind/key in a few row groups, so the zonemaps skip the rest. `SELECT DISTINCT` removes
duplicate findings (for example a gene reported wild-type by two Caris tests on one report).

#### `mart.report`: one row per `unified.report` row

| column | type | definition | vendor source (PLAN.md mapping) |
|---|---|---|---|
| `research_id` | VARCHAR | `r.research_id` | hashed in `deid.py`; unchanged |
| `vendor` | VARCHAR | `r.vendor` | |
| `report_id` | VARCHAR | `r.report_id` | hashed Caris `case_id` / FMI `report_id`; unchanged |
| `year` | INTEGER | `year(r.collected_on)::INTEGER` | Caris specimen collection date; FMI `PMI/CollDate` (shifted) |
| `year_complete` | BOOLEAN | `r.collected_year_complete` | #32; evaluated at build time, current as of the daily rebuild |
| `sex` | VARCHAR | `lower(r.gender)` | Caris `patientInformation.gender`; FMI `PMI/Gender` |
| `age` | INTEGER | Caris tissue only: `max(age_at_collection)` over `caris.specimen` rows with `specimen_kind = 'tumor'` for the case; NULL for Caris liquid and all FMI | Caris `patientAgeatCollection` (capped at 89 by deid). Same rule as `cohort_api.REP`: liquid specimens carry a sentinel |
| `age_band` | VARCHAR | `CASE WHEN age IS NULL THEN 'unknown' WHEN age < 50 THEN '<50' WHEN age < 65 THEN '50-64' WHEN age < 75 THEN '65-74' ELSE '75+' END` | equals `cohort_api.AGE_BANDS` |
| `oncotree` | VARCHAR | `r.oncotree_code` | crosswalk |
| `organ` | VARCHAR | `r.organ_system` | crosswalk |
| `disease` | VARCHAR | `r.disease_text` | crosswalk / vendor text |
| `assay_class` | VARCHAR | `r.assay_class` | |
| `assay_name` | VARCHAR | `r.assay_name` | |
| `purity` | DOUBLE | `r.tumor_purity_pct` | Caris `histopathology.hePercentTumorNuclei`; FMI `purity-assessment` / `percent-tumor-nuclei` |
| `site_type` | VARCHAR | Caris: `lower(trim(site_type))` of the case's first tumor specimen (`specimen_kind = 'tumor'`, lowest `specimen_idx`); NULL for FMI | Caris `specimenSiteType` (`Primary`, `Metastatic`, `Local Recurrence`, `Local Extension`, `Unknown`) |
| `site` | VARCHAR | Caris: `lower(trim(site))` of that same specimen; NULL for FMI | Caris `specimenSite` |
| `has_wts` | BOOLEAN | Caris: true if the case has a `caris.gene_tpm` row with `assay IN ('RNA', 'cfTNA')` **or** any `caris.wts_expression` row; else false. FMI: false (never NULL) | gene TPM CSV file name prefix; `wtsExpression` records |

`has_wts` excludes the `gDNA` TPM files: they are DNA, not transcriptome. Some cases have
`wtsExpression` percentiles but no TPM file, and those count as WTS. Build it from one CTE:
`SELECT DISTINCT case_id FROM caris.gene_tpm WHERE assay IN ('RNA','cfTNA') UNION SELECT DISTINCT case_id FROM caris.wts_expression`,
left-joined on `r.vendor = 'caris' AND w.case_id = r.report_id`.

When a case has several tumor specimens, `site`/`site_type` come from the first one. That is a
`ponytail:` simplification, so mark it with a comment naming the ceiling (later specimens are
not represented) and the upgrade path (one `specimen` fact per specimen).

#### `mart.fact`: one row per finding

Columns, in this order: `research_id` VARCHAR, `vendor` VARCHAR, `report_id` VARCHAR,
`kind` VARCHAR, `key` VARCHAR, `sub` VARCHAR, `val` VARCHAR, `num` DOUBLE, `unit` VARCHAR,
`tier` VARCHAR.

Rules for every arm:

- `research_id`, `vendor`, `report_id` come from the unified view or a join to
  `caris.report` (`case_id`) / `fmi.report` (`report_id`). They are never derived.
- Gene-keyed arms drop `key IS NULL OR key IN ('N/A', '')`, as `cohort_api.ALT` does.
- `unit` is NULL whenever `num` is NULL. `tier` is NULL except on mutation rows.

| kind | key | sub | val | num | unit | tier | source |
|---|---|---|---|---|---|---|---|
| `alteration` | `gene` | `'mutation'` | `regexp_replace(hgvs_p, '^p\.', '')` (NULL when no protein change) | NULL | NULL | `unified.variant.tier`, **all five tiers** | `unified.variant` (Caris `genomicAlteration` gene/hgvsProteinChange/result; FMI `short-variant` @gene/@protein-effect/@status + VUS list) |
| `alteration` | `gene` | `cn_type` ∈ (`'amplification'`, `'loss'`) | NULL | NULL | NULL | NULL | `unified.cna` where `cn_type IN ('amplification','loss')` (Caris `copyNumberType`; FMI `copy-number-alteration/@type`) |
| `alteration` | `gene1`, and `gene2` as a second row when `gene2 <> gene1` | `'fusion'` | the partner gene (`gene2` on the `gene1` row, `gene1` on the `gene2` row) | NULL | NULL | NULL | `unified.fusion` (Caris `translocation` gene1/gene2; FMI `rearrangement` @targeted-gene/@other-gene) |
| `biomarker` | `name` ∈ (`'TMB'`, `'MSI'`, `'LOH'`) | NULL | `call_norm` | `value` | `'mut/Mb'` for TMB, `'%'` for LOH, NULL for MSI | NULL | `unified.biomarker` (Caris `tumorMutationBurden`, `microsatelliteInstability`, `genomicLevelHeterozygosity`; FMI `biomarkers/*`) |
| `ihc` | `name` (`PD-L1`, `ERBB2 (Her2/Neu)`, `ER/PR/Her2/Neu`, `Mismatch Repair Status`, …) | `clone` (PD-L1 only, else NULL) | `call_norm` | `value` | `unit` as in the view (`TPS`, `CPS`, `% stained`) | NULL | `unified.biomarker` where `vendor = 'caris' AND name NOT IN ('TMB','MSI','LOH')` (Caris `expressionAlteration`) |
| `expression` | `gene` | NULL | NULL | `tpm_percentile` | `'percentile'` | NULL | `caris.wts_expression` joined to `caris.report`, `tpm_percentile IS NOT NULL` (Caris `wtsExpression.tpmPercentile`) |
| `tested_negative` | `gene` | `evidence` (`'wildtype'` / `'pertinent_negative'`) | NULL | NULL | NULL | NULL | `unified.gene_tested` (Caris `wildtypeBiomarker`; FMI `PertinentNegatives`) |
| `actionability` | `'caris_level1'` | `biomarker` | `lower(therapy)` | NULL | NULL | NULL | `caris.therapy` joined to `caris.report`, `lower(level) = 'level 1' AND lower(association) = 'benefit'` (Caris `therapies[].therapyRecommendation[]`) |
| `actionability` | `'fmi_fda_any_indication'` | `gene` | `lower(coalesce(generic_name, name))` | NULL | NULL | NULL | `fmi.therapy` joined to `fmi.report`, `fda_approved AND lower(effect) = 'sensitizing' AND include IS NOT false` (`Genes/Gene/Alterations/Alteration/Therapies/Therapy`) |
| `actionability` | `'fmi_trial'` | `gene` | `nct_id` | NULL | NULL | NULL | `fmi.trial` joined to `fmi.report`, `nct_id IS NOT NULL AND include IS NOT false` (`Trials/Trial`) |
| `specimen` | `'site_type'` | NULL | `mart.report.site_type` | NULL | NULL | NULL | `mart.report`, non-NULL only |
| `specimen` | `'site'` | NULL | `mart.report.site` | NULL | NULL | NULL | `mart.report`, non-NULL only |
| `specimen` | `'purity'` | NULL | NULL | `mart.report.purity` | `'%'` | NULL | `mart.report`, non-NULL only |

Notes for the implementer and for whoever writes the compiler next:

- Mutation rows carry every tier, benign included. "Benign never counts as an alteration"
  (#32) is enforced by the compiler's `tier[]` default (`pathogenic`, `likely_pathogenic`),
  not by leaving rows out of the mart. Put a one-line comment above the arm. CNA and fusion
  rows have `tier = NULL`, and a tier filter applies to `sub = 'mutation'` only, the same way
  `cohort_api.ALT` treats them today.
- The alteration arms are exactly `cohort_api.ALT`'s sources, with all tiers kept and a
  partner gene on fusions, so the mart's alteration counts agree with the phase 1 API at
  matching tiers.
- The actionability `key`s are the §3.1 `evidence` vocabulary, so the compiler maps them 1:1.
  Caris levels other than `Level 1`/`Benefit` and FMI `Resistant`/`Unclear_Resistance` or
  non-FDA therapies are not actionability facts. FMI `Include = false` items are not on the
  signed report, so they are left out. `fmi_fda_any_indication` keeps "any indication" in its
  name on purpose (§1 issue 5).
- Specimen facts repeat `mart.report` columns on purpose. `mart.report` serves dimensions and
  pivots, and `mart.fact` lets the specimen criterion use the same `EXISTS` template as
  every other kind.
- TMB `unit` is `'mut/Mb'` for both vendors. FMI's own spelling `mutations-per-megabase` stays
  in `unified.biomarker.unit`.

#### Synthetic example rows

```
mart.report: ('r1…', 'caris', 'a9…', 2025, true, 'female', 89, '75+', 'BRCA', 'Breast', 'Breast Carcinoma',
              'tissue', 'Caris CMI025', NULL, 'primary', 'breast', true)
mart.fact:   ('r1…', 'caris', 'a9…', 'alteration', 'KRAS', 'mutation', 'G12C', NULL, NULL, 'pathogenic')
             ('r1…', 'fmi',   'b7…', 'alteration', 'ALK', 'fusion', 'EML4', NULL, NULL, NULL)
             ('r1…', 'caris', 'a9…', 'ihc', 'PD-L1', '22c3', 'positive', 55.0, 'TPS', NULL)
             ('r1…', 'caris', 'a9…', 'expression', 'TACSTD2', NULL, NULL, 81.0, 'percentile', NULL)
             ('r1…', 'caris', 'a9…', 'tested_negative', 'KRAS', 'wildtype', NULL, NULL, NULL, NULL)
             ('r1…', 'fmi',   'b7…', 'actionability', 'fmi_trial', 'ERBB2', 'NCT00000001', NULL, NULL, NULL)
             ('r1…', 'caris', 'a9…', 'specimen', 'site_type', NULL, 'primary', NULL, NULL, NULL)
```

### What leaves the host, and id stability

- Nothing new leaves. The mart lives only in `genomics.duckdb`, which stays on the host. The
  cohort API, dashboard loader and public site do not read it in this change. When the
  compiler reads it (next issues), every count passes the existing `suppress()` and the §3.6
  additions. The internal tailnet MCP `query` tool already reads the row-level `unified.*`
  views, so `mart.*` adds no new exposure there.
- `research_id`/`report_id`: unchanged. The mart copies them from tables `deid.py` already
  wrote and adds no new hash, key or hash input. A test pins that `mart.report`'s
  `(vendor, report_id, research_id)` set equals `unified.report`'s, and that every
  `mart.fact` key triple is in `mart.report`.

## Acceptance criteria

- [ ] `genomics deid` (synthetic `DATA`) creates `mart.report` and `mart.fact` as
      `BASE TABLE`s (not views) in the de-id file.
- [ ] `mart.report` columns and types are exactly, in order: `research_id` VARCHAR, `vendor`
      VARCHAR, `report_id` VARCHAR, `year` INTEGER, `year_complete` BOOLEAN, `sex` VARCHAR,
      `age` INTEGER, `age_band` VARCHAR, `oncotree` VARCHAR, `organ` VARCHAR, `disease`
      VARCHAR, `assay_class` VARCHAR, `assay_name` VARCHAR, `purity` DOUBLE, `site_type`
      VARCHAR, `site` VARCHAR, `has_wts` BOOLEAN.
- [ ] `mart.fact` columns and types are exactly, in order: `research_id`, `vendor`,
      `report_id`, `kind`, `key`, `sub`, `val` (VARCHAR), `num` DOUBLE, `unit`, `tier`
      (VARCHAR).
- [ ] `mart.report` has one row per `unified.report` row with the same
      `(vendor, report_id, research_id)` set. Every `mart.fact` triple appears in `mart.report`.
- [ ] Every kind (`alteration`, `biomarker`, `ihc`, `expression`, `tested_negative`,
      `actionability`, `specimen`) has at least one row on the synthetic fixture, and no other
      kind appears.
- [ ] The per-kind facts listed in the test plan hold, including the negative cases (Caris
      Level 3 / Lack of Benefit, FMI Resistant and `Include = false` therapy, FMI
      `Include = false` trial give no actionability row).
- [ ] `unit IS NULL` whenever `num IS NULL`. `tier IS NOT NULL` exactly on
      `kind = 'alteration' AND sub = 'mutation'` rows.
- [ ] `unified.biomarker.clone` is `22c3` on the synthetic `PD-L1 (22c3)` rows and NULL on
      every non-PD-L1 row.
- [ ] Existing tests still pass (`test_unified_views`' expected biomarker dict is updated for
      the new fixture rows). No change to research_id/report_id derivation.
- [ ] README Schemas documents `mart.*` (both tables, the per-kind meaning of
      key/sub/val/num/unit/tier, that tier filters apply to mutation rows) and the
      `unified.biomarker.clone` column. `COHORT_DISCOVERY.md` §3.2 and `AGENTS.md` are
      updated per the Files table.
- [ ] `uv run pytest -q` passes. Dashboard `npm test` is unaffected (n/a: no dashboard code).

## Test plan

Everything goes in `tests/test_pipeline.py` on the existing module fixture (synthetic Caris
JSON and FMI XML in a `tmp_path_factory` `DATA`, `genomics load` + `genomics deid` via `uv run`).
It never reads `$DATA/raw` or the PHI file. The tests read only `db.*`.

### Fixture additions (synthetic)

Caris `tests[0].testResults` (append):

```python
{"genomicLevelHeterozygosity": {"result": "High", "LOHpercentage": "21"}},
{"expressionAlteration": {"biomarkerName": "PD-L1 (22c3)", "result": "Positive", "expressionType": "IHC", "tpScore": "55"}},
{"expressionAlteration": {"biomarkerName": "PD-L1 (22c3)", "result": "Positive", "expressionType": "IHC", "cpScore": "12"}},
{"wtsExpression": {"gene": "TACSTD2", "tpm": "40.2", "tpmPercentile": "81"}},
```

Caris `"therapies"` (replace `None`):

```python
[{"therapyRecommendation": [
    {"biomarker": "ERBB2", "method": "IHC", "therapyName": "Trastuzumab", "therapyAssociation": "Benefit", "biomarkerLevel": "Level 1"},
    {"biomarker": "TP53", "method": "NGS", "therapyName": "Olaparib", "therapyAssociation": "Benefit", "biomarkerLevel": "Level 3"},
    {"biomarker": "KRAS", "method": "NGS", "therapyName": "Cetuximab", "therapyAssociation": "Lack of Benefit", "biomarkerLevel": "Level 1"}]}]
```

FMI `FinalReport`: a second `<Gene>` inside `<Genes>`, plus `<Trials>`:

```xml
<Gene><Name>ERBB2</Name><Alterations><Alteration><Name>amplification</Name><Include>true</Include>
  <Interpretation>ERBB2 amplification.</Interpretation>
  <Therapies>
   <Therapy><Name>Trastuzumab</Name><GenericName>trastuzumab</GenericName><FDAApproved>true</FDAApproved><Effect>Sensitizing</Effect><Include>true</Include></Therapy>
   <Therapy><Name>Lapatinib</Name><GenericName>lapatinib</GenericName><FDAApproved>true</FDAApproved><Effect>Resistant</Effect><Include>true</Include></Therapy>
   <Therapy><Name>Neratinib</Name><GenericName>neratinib</GenericName><FDAApproved>true</FDAApproved><Effect>Sensitizing</Effect><Include>false</Include></Therapy>
  </Therapies></Alteration></Alterations></Gene>
...
<Trials>
 <Trial><Gene>ERBB2</Gene><Alteration>amplification</Alteration><NCTID>NCT00000001</NCTID><Title>Synthetic trial A</Title><Include>true</Include></Trial>
 <Trial><Gene>ERBB2</Gene><Alteration>amplification</Alteration><NCTID>NCT00000002</NCTID><Title>Synthetic trial B</Title><Include>false</Include></Trial>
</Trials>
```

The ERBB2 alteration carries an `Interpretation` so that
`test_phi_columns_are_gone_and_ids_are_hashed`'s `fetchone()` on `fmi.alteration.interpretation`
never sees NULL, whatever the row order. None of the new strings match `deid.ID_PATTERN`.

Update `test_unified_views`' expected `bm` dict with `("caris", "LOH"): "high"` and
`("caris", "PD-L1"): "positive"`.

### New tests (names are the contract)

Use `F = "SELECT kind, key, sub, val, num, unit, tier FROM db.mart.fact WHERE vendor = ? AND kind = ?"`
style queries and compare sets.

- `test_mart_tables_are_tables_with_pinned_columns`: `information_schema.tables` gives
  `table_type = 'BASE TABLE'` for both. `information_schema.columns` `(column_name, data_type)`
  in `ordinal_position` order equals the two lists in the acceptance criteria.
- `test_mart_report_rows`: two rows. The `(vendor, report_id, research_id)` set equals
  `unified.report`'s. `year == year(collected_on)` and `year_complete == collected_year_complete`
  from `unified.report`. Caris row: `sex = 'female'`, `age = 89`, `age_band = '75+'`,
  `oncotree = 'BRCA'`, `assay_class = 'tissue'`, `site_type = 'primary'`, `site = 'breast'`,
  `has_wts = true`, `purity IS NULL`. FMI row: `age IS NULL`, `age_band = 'unknown'`,
  `site IS NULL`, `site_type IS NULL`, `has_wts = false`, `purity = 50.0`.
- `test_mart_fact_keys_and_kinds`: every fact triple is in `mart.report`. `DISTINCT kind` equals
  the seven kinds. `count(*) WHERE num IS NULL AND unit IS NOT NULL` = 0.
  `(tier IS NOT NULL) = (kind = 'alteration' AND sub = 'mutation')` for every row.
- `test_mart_fact_alteration`: Caris mutation `(key, tier)` pairs equal
  `{(g, tier) for g, _, _, _, tier in CARIS_TIERS}` (benign included). FMI mutation pairs equal
  `{TP53: pathogenic, PIK3CA: vus, BRAF: likely_pathogenic, ARID1A: unclassified}`. TP53
  `val = 'R175H'` for both vendors (`p.` stripped). `('ERBB2', 'amplification')` for both
  vendors. FMI fusion rows are exactly `{('ALK','fusion','EML4'), ('EML4','fusion','ALK')}`.
- `test_mart_fact_biomarker`: Caris `{('TMB', None, 'high', 22.0, 'mut/Mb'), ('MSI', None, 'stable', None, None), ('LOH', None, 'high', 21.0, '%')}`.
  FMI `{('TMB', None, 'high', 22.0, 'mut/Mb'), ('MSI', None, 'stable', None, None)}`
  (`key, sub, val, num, unit`).
- `test_mart_fact_ihc`: contains `('PD-L1', '22c3', 'positive', 55.0, 'TPS')`,
  `('PD-L1', '22c3', 'positive', 12.0, 'CPS')`,
  `('ERBB2 (Her2/Neu)', None, 'her2-low', 15.0, '% stained')`,
  `('Mismatch Repair Status', None, 'proficient', None, None)`. No FMI `ihc` rows. Also
  `unified.biomarker.clone` is `'22c3'` on PD-L1 rows and NULL elsewhere.
- `test_mart_fact_expression`: Caris rows are exactly `{('TACSTD2', None, None, 81.0, 'percentile')}`.
- `test_mart_fact_tested_negative`: `{('caris','KRAS','wildtype'), ('fmi','KRAS','pertinent_negative')}`
  (`vendor, key, sub`).
- `test_mart_fact_actionability`: all rows are exactly
  `{('caris','caris_level1','ERBB2','trastuzumab'), ('fmi','fmi_fda_any_indication','ERBB2','trastuzumab'), ('fmi','fmi_trial','ERBB2','NCT00000001')}`
  (`vendor, key, sub, val`), so the Level 3, Lack of Benefit, Resistant and `Include = false`
  rows are absent.
- `test_mart_fact_specimen`: Caris `{('site_type', 'primary', None, None), ('site', 'breast', None, None)}`.
  FMI `{('purity', None, 50.0, '%')}` (`key, val, num, unit`).

Commands: `uv run pytest -q`. Dashboard `npm test` is n/a (no dashboard code changes).
`uvx ruff check src mcp tests` is advisory.

## Risks

- **Seam blast radius.** Every phase 1 count will read `mart.fact`, so a wrong arm skews
  every criterion of that kind. The per-kind tests pin each arm on synthetic rows, and the
  "agrees with `cohort_api.ALT`" property means a later real-DB test can compare mart
  alteration counts to the phase 1 API.
- **`deid` failure mode.** An error in `mart.sql` fails the whole `genomics deid` run (after the
  vendor tables and `unified.*` are written, before the leak assert). The systemd unit then
  fails and alerts via ntfy, as any `deid` failure does today. Build time grows by one pass over `unified.*` plus a
  `DISTINCT case_id` scan of `caris.gene_tpm` (seconds on the host).
- **Benign rows in the mart.** A future compiler that forgets the tier default would count
  benign variants. The README and the arm comment say so. The compiler issue should pin the
  default with a test.
- **`year_complete` is frozen at build time.** It is current only as of the last daily rebuild,
  which is fine at daily cadence. If the rebuild stops, the flag goes stale along with the data.
- **First tumor specimen only** for `site`/`site_type`, so multi-specimen Caris cases show
  one site. This is marked `ponytail:` in SQL.
- **Real DB lags the code.** Until the next daily rebuild after merge, the real de-id file has
  no `mart.*`. No real-DB test reads the mart in this change, so nothing skips or fails.
- **Actionability judgement calls** (Caris `Level 1` + `Benefit` only; FMI `Sensitizing` +
  FDA flag + `Include` not false). These follow §3.1's three evidence values and §1 issue 5.
  A domain reviewer may want `Level INDICATED` or other levels later, which would add a key,
  not change the shape.
