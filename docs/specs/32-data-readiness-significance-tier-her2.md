# Spec #32: data readiness — significance tier, HER2 calls, consequence case, partial years

Part of #23, phase 0 of `dashboard/COHORT_DISCOVERY.md` (§1 "Data issues that change counts
today", §4). Labels: `seam` (touches `sql/unified.sql` and the cohort API's allow-lists).

All examples below are synthetic. The vendor vocabulary strings quoted (Caris `result`, FMI
`status`, Caris IHC calls) are the vendors' controlled terms, not patient data; no counts appear.

## Goal

1. `unified.variant.tier`: one significance column with values `pathogenic`,
   `likely_pathogenic`, `vus`, `likely_benign_or_benign`, `unclassified`, derived per vendor.
   The default "pathogenic" filter in the cohort API and the dashboard loader becomes
   `tier IN ('pathogenic', 'likely_pathogenic')`; unclassified is opt-in; benign never counts
   as an alteration.
2. `unified.variant.consequence` is lower case.
3. `unified.biomarker.call_norm` folds the Caris HER2 IHC spelling variants into one vocabulary;
   `call` keeps the raw string. Composite ER/PR/HER2 calls stay separate.
4. `unified.report.collected_year_complete`: whether the report's (date-shifted) collection
   year can still gain reports.
5. Viral calls are not offered as a filter; README says so.

## Non-goals

- No `mart.*` schema (phase 1). The mart will read these columns.
- No change to `deid.py`, the PHI drop lists, id hashing, date shifting or the leak assert.
  `research_id` and `report_id` are untouched (no key, hash input or table copy changes).
- No cross-vendor consequence vocabulary (Caris `Synonymous`/`Silent`, `Splicing` vs FMI
  `splice` stay distinct values; only case is folded). No `'NA'` → NULL mapping.
- No change to how the Biomarkers page shows IHC: it keeps the raw `call` (#22's decision for
  display). HER2 `call_norm` is for cohort filters (phase 1).
- No "unclassified" toggle on the Genes page: the loader shows pathogenic/likely and VUS only;
  unclassified variants leave the Genes page. Discover's `tier[]` criterion is where all tiers
  become selectable.
- No page shading for partial years yet and no partial-year flag in API responses; the column
  is exposed for phase 1 pages to use.
- No viral filter and no code for one.
- No new dependencies.

## Design

### 1. `src/uccc_genomics/sql/unified.sql`

#### `unified.variant`: add `tier`, lower-case `consequence`

Vendor sources (PLAN.md mapping):

| column | Caris source | FMI source |
|---|---|---|
| `tier` | `caris.variant.result` (JSON `result`) and `caris.variant.vus` (JSON `unknownSignificance`) | `fmi.short_variant.status` (`short-variant/@status`) and `fmi.short_variant.is_vus` (`FinalReport/VariantProperties/VariantProperty/@isVUS`) |
| `consequence` | `lower(caris.variant.consequence)` (JSON `molecularConsequence`) | `lower(fmi.short_variant.functional_effect)` (`@functional-effect`) |

Raw values stay available: `vendor_call` (already `v.result` / `v.status`), `is_vus` (unchanged
definition), and the vendor tables `caris.variant.consequence` / `fmi.short_variant.functional_effect`.

Caris branch, added column (replace `v.consequence` with `lower(v.consequence) AS consequence`):

```sql
CASE WHEN lower(v.result) IN ('pathogenic variant', 'mutated, pathogenic') THEN 'pathogenic'
     WHEN lower(v.result) IN ('likely pathogenic variant', 'mutated, presumed pathogenic') THEN 'likely_pathogenic'
     WHEN lower(v.result) IN ('variant of uncertain significance', 'mutated, variant of unknown significance')
          OR v.vus THEN 'vus'
     WHEN lower(v.result) IN ('likely benign variant', 'benign variant', 'mutated, presumed benign') THEN 'likely_benign_or_benign'
     ELSE 'unclassified' END AS tier
```

FMI branch, added column (replace `v.functional_effect AS consequence` with
`lower(v.functional_effect) AS consequence`):

```sql
CASE WHEN v.is_vus THEN 'vus'
     WHEN lower(v.status) = 'known' THEN 'pathogenic'
     WHEN lower(v.status) = 'likely' THEN 'likely_pathogenic'
     ELSE 'unclassified' END AS tier
```

Add a two-line comment above the view: tier is what every filter uses; `is_vus` and
`vendor_call` are kept as the vendor's own flags.

Mapping table (every row is pinned by a test):

| vendor | vendor value | tier |
|---|---|---|
| caris | `Pathogenic Variant`, `Mutated, Pathogenic` | pathogenic |
| caris | `Likely Pathogenic Variant`, `Mutated, Presumed Pathogenic` | likely_pathogenic |
| caris | `Variant of Uncertain Significance`, `Mutated, Variant of Unknown Significance`, or `unknownSignificance = true` with an unlisted result | vus |
| caris | `Likely Benign Variant`, `Benign Variant`, `Mutated, Presumed Benign` | likely_benign_or_benign |
| caris | `Mutated, Unclassified` (**decided** in the issue), `Risk Allele`, any other or NULL result | unclassified |
| fmi | `is_vus = true` (any status) | vus |
| fmi | status `known` | pathogenic |
| fmi | status `likely` | likely_pathogenic |
| fmi | status `unknown` with `is_vus = false` (**decided** in the issue), or `is_vus` NULL (FoundationOne Monitor files have no FinalReport, so no VUS list), or any other status | unclassified |

Judgement calls the issue does not spell out, made here so the implementer doesn't have to:
"Presumed Pathogenic/Benign" are read as "likely"; `Risk Allele` (a low-penetrance germline
allele) is `unclassified`, so it leaves the default pathogenic filter and is opt-in like the
other unclassified rows; unknown future Caris terms default to `unclassified` (out of the default
filter rather than silently counted as pathogenic).

#### `unified.biomarker`: HER2 spelling fold

Add a branch to the existing `call_norm` CASE, before the final `ELSE lower(call)`:

```sql
WHEN name = 'ERBB2 (Her2/Neu)' THEN
  CASE WHEN lower(call) IN ('her2-positive', 'positive') THEN 'positive'
       WHEN lower(call) IN ('her2-negative', 'negative') THEN 'negative'
       WHEN lower(call) IN ('her2-low', 'low') THEN 'her2-low'
       WHEN lower(call) = 'her2-ultralow' THEN 'her2-ultralow'
       WHEN lower(call) = 'her2-null' THEN 'her2-null'
       ELSE lower(call) END
```

Source: `caris.ihc.result` (JSON `result`) where `caris.ihc.biomarker_name` is
`ERBB2 (Her2/Neu)`. Resulting vocabulary: `positive`, `negative`, `equivocal`, `her2-low`,
`her2-ultralow`, `her2-null`, plus anything else lower-cased as reported (`insufficient tumor`,
`other`). The breast scale (low/ultralow/null) is **not** folded into positive/negative; only
spellings of the same result are merged, which is the line #22 drew (it allowed the MMR spelling
fold for the same reason). The composite marker `ER/PR/Her2/Neu` is a different `name` and keeps
`call_norm = lower(call)` (`hr-positive her2-low`, `triple negative`), so it never mixes with the
single-marker `her2-low`. Update the comment above the CASE accordingly. `call` stays raw.

#### `unified.report`: `collected_year_complete`

Wrap the existing two-branch union the way `unified.biomarker` is wrapped:

```sql
CREATE OR REPLACE VIEW unified.report AS
SELECT *,
       -- deid.py shifts every date by up to ±182 days per patient, so shifted year Y can still
       -- gain reports until real collections through Dec 31 of Y + 182 days have happened.
       make_date(year(collected_on), 12, 31) + 182 < current_date AS collected_year_complete
FROM ( <existing caris SELECT> UNION ALL BY NAME <existing fmi SELECT> );
```

`DATE + INTEGER` is a `DATE` in DuckDB (checked on 1.5.5). NULL `collected_on` gives NULL. The
182 must match `shift_days` in `deid.py` (`% 365 - 182`); the comment names it. Evaluated at
query time; the daily rebuild keeps it current. Example: on 2026-10-25, years ≤ 2025 are
complete; 2026 and later (date-shift spillover) are not.

`unified.patient` reads `unified.report` and needs no change.

### 2. `mcp/src/uccc_genomics_mcp/cohort_api.py`

- `ALT_CLASSES = ["pathogenic", "vus", "unclassified", "amplification", "loss", "fusion"]`.
- New `OPT_IN_CLASSES = ("vus", "unclassified")`; in `parse()` the default becomes
  `p["alt_class"] = [c for c in ALT_CLASSES if c not in OPT_IN_CLASSES]`.
- `ALT` CTE, variant arm:

  ```sql
  SELECT vendor, report_id, gene,
         CASE WHEN tier IN ('pathogenic', 'likely_pathogenic') THEN 'pathogenic' ELSE tier END AS alt_class,
         regexp_replace(hgvs_p, '^p\\.', '') AS aa
  FROM unified.variant
  WHERE tier IN ('pathogenic', 'likely_pathogenic', 'vus', 'unclassified')
    AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
  ```

  `likely_benign_or_benign` rows never enter `alt`, so they are neither countable nor in the
  gene/aa vocabularies. Update the comment above `ALT`.
- Small-cell rule: unchanged. The new class only adds cells to `by_alt_class`, which goes
  through `suppress()` (floor, secondary suppression, whole-cohort rule) like every other list.
  The `gene` and `aa` vocabularies stay floored at `MIN_CELL` patients by `VOCAB_SQL`. Parameters
  stay allow-listed and bound.

### 3. `dashboard/src/components/cohort.js` (+ `dashboard/test/cohort.test.js`)

- `export const OPT_IN_CLASSES = ["vus", "unclassified"];` and replace both
  `options.alt_class.filter((c) => c !== "vus")` (in `cohortQuery` and `readQuery`) with
  `options.alt_class.filter((c) => !OPT_IN_CLASSES.includes(c))`. Update the comment ("every
  class except VUS and unclassified").
- No change to `cohort.md`: its checkbox renders `options.alt_class`, so "unclassified" appears
  unticked.

### 4. `dashboard/src/data/summary.json.py`

- `ALT`: variant arm becomes
  `CASE WHEN tier = 'vus' THEN 'VUS' ELSE 'pathogenic/likely' END AS alt_type ... FROM unified.variant
  WHERE gene IS NOT NULL AND tier IN ('pathogenic', 'likely_pathogenic', 'vus')`.
- `gene_variant` and `vaf_hist`: replace `NOT coalesce(v.is_vus, false)` with
  `v.tier IN ('pathogenic', 'likely_pathogenic')`.
- Small-cell rule: unchanged (`rows()` drops `n`/`n_patients` under `MIN_CELL`; the self-check
  at the bottom still runs). Fewer rows qualify, never more granular ones.

### 5. Docs (same PR)

- `mcp/src/uccc_genomics_mcp/server.py` schema text: add `tier` (with its five values) to the
  `unified.variant` columns, note `consequence` is lower case, add `collected_year_complete` to
  `unified.report`, mention the HER2 `call_norm` vocabulary under `unified.biomarker`; example 3
  uses `v.tier IN ('pathogenic', 'likely_pathogenic')` instead of `NOT coalesce(v.is_vus, false)`.
- `README.md`: in the `unified.*` paragraph, one sentence each on `variant.tier`, lower-case
  `consequence`, HER2 `call_norm`, `report.collected_year_complete`. Add a short "Known gaps"
  section (before "Not in scope"): FMI viral calls (`fmi.non_human`) are loaded but not offered
  as a cohort filter until someone with domain knowledge has reviewed them (COHORT_DISCOVERY.md
  §1 item 4).
- `dashboard/COHORT_TOOL.md` line on `alt_class`: "pathogenic (pathogenic or likely pathogenic
  tier), vus, unclassified, amplification, loss, fusion (default: everything except vus and
  unclassified)".
- `dashboard/COHORT_DISCOVERY.md`: §3.2 says the phase 0 normalisation "happens once in
  `mart.sql`". This spec puts it in `unified.sql` (as the issue requires), and `mart.sql` will
  read it; change that sentence. In §5, mark question 1 as decided in #32 (Mutated, Unclassified
  and FMI unknown/not-VUS are `unclassified`, opt-in).

## Acceptance criteria

- [ ] `unified.variant` has `tier` with exactly the five values and the mapping table above;
      every row of that table is asserted in `tests/test_pipeline.py`.
- [ ] `unified.variant.consequence` has no upper-case characters; vendor tables keep the raw case.
- [ ] `unified.biomarker.call_norm` for `ERBB2 (Her2/Neu)` follows the HER2 table; `call` is
      unchanged; `ER/PR/Her2/Neu` composite calls are lower-cased only and never equal `her2-low`.
- [ ] `unified.report.collected_year_complete` equals
      `make_date(year(collected_on), 12, 31) + 182 days < today` for every report.
- [ ] Cohort API: `alt_class` vocabulary is `pathogenic, vus, unclassified, amplification, loss,
      fusion`; default excludes `vus` and `unclassified`; `pathogenic` counts pathogenic and
      likely-pathogenic tiers; benign variants never count and their genes are not in the
      vocabulary on their own.
- [ ] `cohort.js` defaults exclude both opt-in classes; `npm test` passes.
- [ ] Dashboard loader filters on `tier`, no `is_vus` reference remains in
      `summary.json.py` or `cohort_api.py`.
- [ ] No change to `deid.py`; `research_id`/`report_id` behaviour unchanged (existing pipeline
      tests pass unmodified in their id/date assertions).
- [ ] README "Known gaps" names the viral-call hold; docs listed in §5 updated.
- [ ] `uv run --all-packages pytest -q` and `cd dashboard && npm ci && npm test` pass.

## Test plan

All synthetic, built in temp dirs; nothing reads `$DATA/raw` or the PHI file.

### `tests/test_pipeline.py` (synthetic Caris JSON / FMI XML → load → deid in a temp `DATA`)

Fixture changes (same single patient, same two reports, so patient/date tests keep passing):

- Caris TP53 record: add `"molecularConsequence": "Missense"`.
- Append one `genomicAlteration` per Caris mapping row to `CARIS["tests"][0]["testResults"]`,
  built from a module constant
  `CARIS_TIERS = [(gene, result, unknown_significance, hgvs_p, tier), ...]`:

  | gene | result | unknownSignificance | hgvsProteinChange | tier |
  |---|---|---|---|---|
  | TP53 (existing) | Pathogenic Variant | false | p.R175H | pathogenic |
  | BRCA2 | Mutated, Pathogenic | – | p.S1982fs | pathogenic |
  | ATM | Likely Pathogenic Variant | – | p.R3008C | likely_pathogenic |
  | PTEN | Mutated, Presumed Pathogenic | – | p.R130Q | likely_pathogenic |
  | NF1 | Variant of Uncertain Significance | – | p.A100T | vus |
  | RB1 | Mutated, Variant of Unknown Significance | true | p.A200T | vus |
  | MLH1 | New Caris Term | true | p.A700T | vus |
  | SMAD4 | Likely Benign Variant | – | p.A300T | likely_benign_or_benign |
  | CDH1 | Benign Variant | – | p.A400T | likely_benign_or_benign |
  | STK11 | Mutated, Presumed Benign | – | p.A500T | likely_benign_or_benign |
  | ARID1A | Mutated, Unclassified | – | p.A600T | unclassified |
  | APC | Risk Allele | – | p.I1307K | unclassified |
  | MSH2 | New Caris Term | – | p.A800T | unclassified |

- FMI XML: add `<short-variant gene="BRAF" ... protein-effect="V600E" status="likely"
  functional-effect="missense"/>` and `<short-variant gene="ARID1A" ... protein-effect="Q100*"
  status="unknown" functional-effect="Nonsense"/>` (not in `VariantProperties`, so
  `is_vus = false`).
- Append HER2 IHC records (`biomarkerName` `ERBB2 (Her2/Neu)`) with results `Low`,
  `HER2-Positive`, `Positive`, `HER2-Negative`, `Negative`, `HER2-Null`, `HER2-Ultralow`,
  `Equivocal`, `Insufficient Tumor` (the existing `HER2-Low` stays), and two composite records
  (`biomarkerName` `ER/PR/Her2/Neu`) with `HR-Positive HER2-Low` and `Triple Negative`.

Existing assertions to narrow (not weaken):
- `test_unified_views` variant list: add `WHERE gene IN ('TP53', 'PIK3CA')`; expected list unchanged.
- `test_unified_views` biomarker dict: exclude names `ERBB2 (Her2/Neu)` and `ER/PR/Her2/Neu`
  (now multi-row, covered by the new HER2 test); the `call, value, unit` query adds
  `AND call = 'HER2-Low'`.

New tests:
- `test_variant_tier_maps_every_vendor_value`: `{(vendor, gene): tier}` from `db.unified.variant`
  equals the expected dict built from `CARIS_TIERS` plus FMI
  `{TP53: pathogenic, PIK3CA: vus, BRAF: likely_pathogenic, ARID1A: unclassified}`; and
  `SELECT DISTINCT tier` ⊆ the five values.
- `test_consequence_is_lower_case`: `(caris, TP53)` consequence is `missense`, `(fmi, ARID1A)` is
  `nonsense`, no row has `consequence <> lower(consequence)`; `db.caris.variant` still has
  `Missense` for TP53.
- `test_her2_calls_fold_spellings_only`: `{(name, call): call_norm}` for the two HER2 names equals
  the table in Design §1 (both `HER2-Low` and `Low` → `her2-low`, `HER2-Positive`/`Positive` →
  `positive`, `HER2-Negative`/`Negative` → `negative`, `HER2-Null` → `her2-null`,
  `HER2-Ultralow` → `her2-ultralow`, `Equivocal` → `equivocal`, `Insufficient Tumor` →
  `insufficient tumor`, composite `HR-Positive HER2-Low` → `hr-positive her2-low`,
  `Triple Negative` → `triple negative`).
- `test_collected_year_complete`: for every row of `db.unified.report`,
  `collected_year_complete == (date(collected_on.year, 12, 31) + timedelta(days=182) < date.today())`
  and it is not NULL.

### `tests/test_cohort_api.py` (synthetic DuckDB)

- `build()`: `unified.variant` gains `tier VARCHAR`. Existing rows: colorectal TP53 → `pathogenic`;
  pancreatic TP53 (p0–p2) → `likely_pathogenic` (so the existing 15-patient TP53 R175H answers
  now also prove pathogenic + likely pathogenic merge); melanoma BRAF → `pathogenic`; melanoma
  KRAS G12C → `vus`. New rows: melanoma m12–m17 `NRAS` `Q61K` → `unclassified`; colorectal c0–c5
  `APC` `I1307K` → `likely_benign_or_benign`. No new reports, so `test_health` stays 43.
- `test_unclassified_is_opt_in`: `gene=NRAS` → `patients == 0`; `gene=NRAS&alt_class=unclassified`
  → 6.
- `test_benign_is_never_an_alteration`: `gene=APC` → 400 naming `gene`.
- Add `{"gene": "NRAS", "alt_class": "unclassified"}` to `QUERIES` (no small numbers, no ids).
- `test_vocabularies_are_floored`: expected `aa` adds `"NRAS": ["Q61K"]`; `alt_class` equals the
  new list.
- `test_real_db_matches_hand_written_sql`: the hand-written `hit` uses
  `tier IN ('pathogenic', 'likely_pathogenic')` instead of `NOT coalesce(is_vus, false)`.

### `dashboard/test/cohort.test.js`

- `options.alt_class` fixture gains `"unclassified"`.
- New test: `readQuery("", options).alt_class` equals `["pathogenic", "amplification", "loss",
  "fusion"]`, and `cohortQuery({...all, gene: ["TP53"]}, options) === "gene=TP53"`.
- Existing "partial groups, VUS …" test still produces the same string.

### Real-DB checks (pipeline host, read-only, run by pytest)

`tests/test_dashboard_loaders.py` (sections non-empty, no small cells, no ids) and the cohort
API real-DB test run as today.

## Risks

- **Counts change on purpose.** Caris "Mutated, Unclassified", "Likely Benign", "Benign",
  "Presumed Benign" and "Risk Allele" rows and FMI unknown/not-VUS rows leave the default
  pathogenic counts on the cohort page and Genes page. That is the issue's intent; expect
  smaller numbers after the next build.
- **`Risk Allele` → unclassified** is this spec's call, not the issue's. If it should count as
  pathogenic, it's a one-line move in the Caris CASE plus one fixture row.
- **HER2 `HER2-Negative`/`Negative` fold**: treated as spelling of the same result, like
  `HER2-Low`/`Low`. If someone reads `HER2-Negative` as the pre-HER2-low breast scale (covering
  today's low/ultralow), the fold would blur that; `call` keeps the raw string either way.
- **Partial-year rule ignores reporting lag** (collection to delivery takes weeks), so a year
  flips to complete a little early. The 182-day constant is duplicated from `deid.py`; if the
  shift window ever changes, both must change (comment says so). Only the trailing edge is
  flagged; the first year of data is not marked partial.
- **New Caris terms** fall into `unclassified` silently. They stay visible in `vendor_call`, and
  the tier test pins that behaviour, but nobody is alerted.
- **`unified.sql` is a seam**: every consumer (cohort API, loader, MCP free SQL, future mart)
  reads these views. The change only adds columns and lower-cases one; the existing column set
  and `UNION ALL BY NAME` shape are kept.
