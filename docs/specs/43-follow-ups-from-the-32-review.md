# Spec #43: follow-ups from the #32 review

Issue #43 lists five minor/nit findings from the #32 review that weren't fixed before merge.
This spec fixes all five in one PR. Each is small, and they share the tier tests and docs.

## Goal

1. **code-r0-1**: `tests/conftest.py:deid_lacks_tier()` must not break test collection when the
   real de-id file can't be opened, and spec #32's test plan must say that real-DB tests skip
   until the de-id file is rebuilt with `tier`.
2. **code-r0-2**: every row of the #32 tier mapping table has a fixture. The missing ones are FMI
   `is_vus` NULL (FoundationOne Monitor, no FinalReport), an FMI status other than
   known/likely/unknown, and a Caris NULL `result`.
3. **code-r0-3**: the Caris `tier` vus branch uses the same predicate as `is_vus`, so the two
   columns can't contradict each other.
4. **code-r0-4**: `OPT_IN_CLASSES` in `dashboard/src/components/cohort.js` gets its own comment
   and stops splitting the `GROUPS` comment from `GROUPS`.
5. **code-r0-5**: `dashboard/COHORT_TOOL.md` describes the `gene` vocabulary correctly.

## Non-goals

- No change to `deid.py`, the PHI column lists, id hashing, date shifting or the leak assert.
  `research_id` and `report_id` behave exactly as before.
- No change to the FMI tier CASE, the benign/pathogenic Caris lists, `is_vus`, `mart.sql`, the
  cohort API (`cohort_api.py`), the dashboard loader or MCP tools. Only the Caris `tier` CASE
  changes.
- `deid_lacks_tier()` stays. The daily rebuild runs from the main checkout
  (`systemd/genomics.service` `WorkingDirectory`), so when `tier` lands in the real file depends
  on when that checkout is updated. That isn't known here, so the guard stays until a later
  change removes it.
- No new dependencies.

## Design

### 1. `src/uccc_genomics/sql/unified.sql`: Caris `tier` vus branch (code-r0-3)

Vendor sources are unchanged from #32 (PLAN.md mapping): `caris.variant.result` (JSON `result`)
and `caris.variant.vus` (JSON `unknownSignificance`).

In the Caris branch of `unified.variant`, replace the vus `WHEN`. The full CASE becomes:

```sql
CASE WHEN lower(v.result) IN ('pathogenic variant', 'mutated, pathogenic') THEN 'pathogenic'
     WHEN lower(v.result) IN ('likely pathogenic variant', 'mutated, presumed pathogenic') THEN 'likely_pathogenic'
     WHEN v.vus OR v.result ILIKE '%uncertain significance%' OR v.result ILIKE '%unknown significance%' THEN 'vus'
     WHEN lower(v.result) IN ('likely benign variant', 'benign variant', 'mutated, presumed benign') THEN 'likely_benign_or_benign'
     ELSE 'unclassified' END AS tier
```

The vus predicate is the same expression as `is_vus` on the same row. The pathogenic and
likely_pathogenic branches stay ahead of it. The two previously listed vus terms
(`Variant of Uncertain Significance`, `Mutated, Variant of Unknown Significance`) both contain
one of the phrases, so they still map to vus. What's new: any other result containing
"uncertain significance" or "unknown significance" now maps to vus instead of unclassified.

So for Caris: if `is_vus` is true, `tier` is `vus` unless the result is one of the four
pathogenic/likely-pathogenic terms. If `tier` is `vus`, then `is_vus` is true.

Keep the existing two-line comment above the view, which points to spec #32 for the mapping.

### 2. `tests/conftest.py`: `deid_lacks_tier()` (code-r0-1)

The signature stays `deid_lacks_tier()` and still returns a bool. Wrap the open and the
`DESCRIBE` so a failure returns `False`:

```python
import os

import duckdb

from uccc_genomics.config import DEID_DB


def deid_lacks_tier():
    """True while the real de-id file predates `unified.variant.tier` (#32), until the next daily rebuild.

    Real-DB tests skip then instead of failing; synthetic tests cover the columns meanwhile. Runs at
    collection time (inside skipif), so a file that can't be opened (e.g. mid-rebuild) returns False:
    the real-DB tests then fail on their own, and collection of the synthetic tests isn't affected.
    """
    if not os.path.exists(DEID_DB):
        return False
    from uccc_genomics_mcp import server
    try:
        con = server.get_db()
        try:
            return "tier" not in {r[0] for r in con.execute("DESCRIBE unified.variant").fetchall()}
        finally:
            con.close()
    except (duckdb.Error, OSError):
        return False
```

`server.get_db()` raises `FileNotFoundError` (an `OSError`) when the key file is missing, and
`duckdb.IOException` on a bad or missing file. A missing view raises `duckdb.CatalogException`.
In duckdb 1.5.5 (checked here), `IOException` and `CatalogException` both subclass
`duckdb.Error`. `duckdb` is already a root dependency. Callers in `tests/test_cohort_api.py`
and `tests/test_dashboard_loaders.py` don't change.

### 3. `tests/test_pipeline.py`: fixtures for the missing mapping rows (code-r0-2, code-r0-3)

**Caris rows.** Append two entries to `CARIS_TIERS`. They flow into the Caris JSON, into
`test_variant_tier_maps_every_vendor_value` and into `test_mart_fact_alteration`, all through
the existing comprehensions:

| gene | result | unknownSignificance | hgvsProteinChange | tier |
|---|---|---|---|---|
| BRIP1 | Mutated, Variant of Uncertain Significance | – (absent) | p.A910T | vus |
| KMT2D | `None` (JSON `null`) | – (absent) | p.A920T | unclassified |

BRIP1 pins code-r0-3: today it maps to `unclassified` with `is_vus = true`. KMT2D is the Caris
NULL-`result` row. `caris_variant()` already writes `"result": None`, which `caris.variant.result`
reads as NULL. `wildtype` is false (no `wildtypeBiomarker`), so the row stays in
`unified.variant`. No other change to `caris_variant()`.

At the end of `test_variant_tier_maps_every_vendor_value`, add:

```python
    # Caris tier and is_vus agree; no fixture row has a pathogenic term together with unknownSignificance.
    assert one(db, "SELECT count(*) FROM db.unified.variant "
                   "WHERE vendor = 'caris' AND coalesce(is_vus, false) <> (tier = 'vus')") == (0,)
```

**FMI Monitor rows (FMI `is_vus` NULL, plus an unlisted status).** The main fixture models one
patient with two reports, and most tests assert on that. Adding a third report there would
change patient/report counts, the `collected_year_complete` non-NULL check and the per-vendor
mart rows. So the Monitor file goes in its own small pipeline run instead:

- Pull the body of the `db` fixture out into a module-level helper:

  ```python
  def pipeline(data, fmi_files):
      """Write CARIS (+ its TPM CSV) and `fmi_files` ({file name: XML text}) under raw/ in `data`,
      run load for both vendors and deid, and return a connection with the de-id file attached
      as `db` and the PHI file as `phi`, both read-only."""
  ```

  The body is the current fixture code, unchanged except that the FMI writes become
  `for name, text in fmi_files.items(): open(f"{data}/raw/fmi/{name}", "w").write(text)`.
- `db` becomes:

  ```python
  @pytest.fixture(scope="module")
  def db(tmp_path_factory):
      # broken.xml must fail to parse and land in fmi.load_error rather than abort the load.
      return pipeline(str(tmp_path_factory.mktemp("data")),
                      {"ORD-0001234-01.xml": FMI, "broken.xml": "<ResultsReport><nothing/></ResultsReport>"})
  ```

- New module constant `FMI_MONITOR`. It is a FoundationOne Monitor-style file: a `variant-report`
  with no `FinalReport`, so `fmi.rows_for` takes the report id from the file name and sets
  `is_vus` to NULL. Synthetic values only:

  ```python
  # FoundationOne Monitor files have no FinalReport (no PMI, no VariantProperties), so is_vus is NULL.
  FMI_MONITOR = """<?xml version="1.0"?>
  <ResultsReport>
   <variant-report xmlns="http://foundationmedicine.com/compbio/variant-report-external"
       disease="Breast" disease-ontology="Breast carcinoma (NOS)" gender="female" test-type="FoundationOne Monitor">
    <short-variants>
     <short-variant gene="KRAS" cds-effect="35G>A" protein-effect="G12D" status="known" functional-effect="missense"/>
     <short-variant gene="NRAS" cds-effect="181C>A" protein-effect="Q61K" status="likely" functional-effect="missense"/>
     <short-variant gene="TP53" cds-effect="818G>A" protein-effect="R273H" status="unknown" functional-effect="missense"/>
     <short-variant gene="EGFR" cds-effect="2369C>T" protein-effect="T790M" status="new-fmi-status" functional-effect="missense"/>
    </short-variants>
   </variant-report>
  </ResultsReport>
  """
  ```

- New fixture and test:

  ```python
  @pytest.fixture(scope="module")
  def monitor_db(tmp_path_factory):
      return pipeline(str(tmp_path_factory.mktemp("monitor")), {"ORD-0005678-01.xml": FMI_MONITOR})


  def test_variant_tier_fmi_without_final_report(monitor_db):
      """Monitor files have no VUS list (is_vus NULL); tier still follows status, and an unlisted status is unclassified."""
      got = {r[0]: (r[1], r[2]) for r in monitor_db.execute(
          "SELECT gene, is_vus, tier FROM db.unified.variant WHERE vendor = 'fmi'").fetchall()}
      assert got == {"KRAS": (None, "pathogenic"), "NRAS": (None, "likely_pathogenic"),
                     "TP53": (None, "unclassified"), "EGFR": (None, "unclassified")}
  ```

I ran this file through `genomics load` + `deid` in a scratch `DATA` dir while writing the spec.
The `monitor_db` run takes about 1 s, `deid` and its leak assert pass (the file-name report id is
the hashed key column), and the query returns exactly the dict above. The Monitor patient has no
MRN or names, so `research_id` uses the existing `'nopid:' || vendor || id` path in `deid.py`,
which doesn't change.

After this, the #32 mapping rows and their fixtures line up as follows:

| vendor | mapping row | fixture |
|---|---|---|
| caris | pathogenic terms | TP53, BRCA2 |
| caris | likely pathogenic terms | ATM, PTEN |
| caris | vus terms / `unknownSignificance` / phrase match | NF1, RB1, MLH1, **BRIP1** |
| caris | benign terms | SMAD4, CDH1, STK11 |
| caris | Mutated, Unclassified / Risk Allele / other / NULL result | ARID1A, APC, MSH2, **KMT2D** |
| fmi | `is_vus = true` | PIK3CA (`db`) |
| fmi | status known / likely | TP53, BRAF (`db`); **KRAS, NRAS with `is_vus` NULL** (`monitor_db`) |
| fmi | unknown with `is_vus = false` / `is_vus` NULL / other status | ARID1A (`db`); **TP53, EGFR** (`monitor_db`) |

### 4. `dashboard/src/components/cohort.js` (code-r0-4)

Move `OPT_IN_CLASSES` above the `GROUPS` comment and give it its own one-line comment. No code
change:

```js
// alt_class values the API leaves out unless asked for.
export const OPT_IN_CLASSES = ["vus", "unclassified"];

// Checkbox groups start fully checked; all checked means no filter, so it is left out of the query.
const GROUPS = ["sex", "age", "vendor", "assay_class"];
```

### 5. Docs (code-r0-5, and the doc updates that follow from 1 and 3)

- `dashboard/COHORT_TOOL.md`, `gene` row of the parameter table: replace "genes with at least
  one non-VUS alteration" with "genes with any non-benign alteration (at least `MIN_CELL`
  patients)". `VOCAB_SQL` takes `gene` from `alt`. That covers pathogenic, likely-pathogenic,
  VUS and unclassified variants plus amplification, loss and fusion, kept when the gene has at
  least `MIN_CELL` distinct patients.
- `docs/specs/32-data-readiness-significance-tier-her2.md`:
  - In the Caris CASE block under "`unified.variant`: add `tier`", replace the vus `WHEN` with
    the predicate from Design §1.
  - In the mapping table, change the Caris vus row's value cell to: "`Variant of Uncertain
    Significance`, `Mutated, Variant of Unknown Significance`, any other result containing
    'uncertain significance' or 'unknown significance', or `unknownSignificance = true`, unless
    the result is a pathogenic/likely-pathogenic term (#43)". In the Caris unclassified row,
    "any other or NULL result" stays as it is.
  - Under "Real-DB checks", append: "Real-DB tests skip (`tests/conftest.py:deid_lacks_tier`)
    until the real de-id file is rebuilt with `tier`."

  `unified.sql` names this spec as the place to find the tier mapping, so it's corrected in
  place rather than left stale.
- No change to README.md, PLAN.md, ARCHITECTURE.md, COHORT_DISCOVERY.md or the MCP schema text.
  None of them describe the Caris vus predicate or the gene vocabulary at this level.

### What leaves the de-id file

Nothing new. No loader, endpoint, MCP tool or export is added or changed. The only data-facing
change is the Caris `tier` value for results that contain the VUS phrases without being one of
the two listed terms. `tier` already flows to the cohort API (floored counts, secondary
suppression, whole-cohort rule), the dashboard loader (`MIN_CELL = 5`) and `mart.fact` under
their existing rules. Those rows may move from `unclassified` to `vus`. Both are opt-in classes,
so default cohort counts don't change.

## Acceptance criteria

- [ ] The Caris `tier` CASE in `unified.sql` matches Design §1. The FMI branch and every other
      column are unchanged (`git diff` touches only the vus `WHEN` line(s) in the Caris branch).
- [ ] `CARIS_TIERS` has the BRIP1 (`vus`) and KMT2D (NULL result, `unclassified`) rows, and
      `test_variant_tier_maps_every_vendor_value` and `test_mart_fact_alteration` pass with them.
- [ ] `test_variant_tier_maps_every_vendor_value` asserts that Caris `is_vus` and `tier = 'vus'`
      agree on every fixture row. Against the pre-change `unified.sql`, the BRIP1 row and this
      assertion fail.
- [ ] `test_variant_tier_fmi_without_final_report` exists, uses the `monitor_db` fixture
      (separate temp `DATA`, `FMI_MONITOR` only) and asserts `is_vus` NULL with tiers
      pathogenic / likely_pathogenic / unclassified / unclassified for known / likely /
      unknown / `new-fmi-status`.
- [ ] The `db` fixture writes the same files as before, plus the two new Caris rows. Every
      pre-existing test in `tests/test_pipeline.py` passes with its assertions unmodified (only
      fixture plumbing moves into `pipeline()`).
- [ ] `deid_lacks_tier()` returns False instead of raising when `server.get_db()` or the
      `DESCRIBE` raises `duckdb.Error` or `OSError`.
- [ ] `cohort.js`: `OPT_IN_CLASSES` sits above the `GROUPS` comment with its own one-line comment;
      `npm test` passes.
- [ ] `COHORT_TOOL.md` `gene` row and spec #32 (CASE block, Caris vus mapping row, real-DB skip
      line) are updated as in Design §5.
- [ ] No change to `deid.py`; `research_id`/`report_id` id and date assertions pass unmodified.
- [ ] `uv run pytest -q` and `cd dashboard && npm ci && npm test` pass.

## Test plan

Everything here is synthetic and built in pytest temp dirs. Nothing reads `$DATA/raw` or the PHI
file.

- `tests/test_pipeline.py` (synthetic Caris JSON / FMI XML → `genomics load` → `genomics deid`
  under a temp `DATA`):
  - `CARIS_TIERS` gains BRIP1 and KMT2D (Design §3). They're checked by
    `test_variant_tier_maps_every_vendor_value` (tier per gene, plus the new `is_vus`/`tier`
    agreement assertion) and by `test_mart_fact_alteration` (`mart.fact` keeps every tier).
  - New `monitor_db` fixture plus `test_variant_tier_fmi_without_final_report` (Design §3).
  - Regression check for the implementer: before editing `unified.sql`, run
    `uv run pytest -q tests/test_pipeline.py -k tier` and confirm the BRIP1 expectation fails.
    After the edit it should pass.
- `tests/conftest.py`: no new test. The change is a guard on test infrastructure. The checks are
  that `uv run pytest -q` collects and runs `tests/test_cohort_api.py` and
  `tests/test_dashboard_loaders.py` as before. With the real de-id file present but still
  without `tier`, the real-DB tests are reported as skipped, not as errors.
- `dashboard/test/cohort.test.js`: unchanged; `npm test` must still pass after the move.
- Real-DB checks (pipeline host, read-only, run by pytest): `test_real_db_matches_hand_written_sql`
  and `tests/test_dashboard_loaders.py` behave as today (they skip while the real file lacks
  `tier`).

## Risks

- **Counts move between opt-in classes.** In the real data, Caris results that contain a VUS
  phrase but aren't one of the two listed terms move from `unclassified` to `vus`. Both classes
  are opt-in in the cohort API and on the page, so default counts don't change. Counts with
  `alt_class=vus` or `alt_class=unclassified` can shift after the next rebuild, and so can MCP
  free-SQL results that group by `tier`.
- **Pathogenic plus `unknownSignificance = true`** keeps `tier = pathogenic`/`likely_pathogenic`
  while `is_vus` is true. That's intended (the vendor's explicit significance term wins), but
  the two columns can still disagree for those rows. The new agreement assertion is
  fixture-scoped and documents that exception in its comment.
- **Extra pipeline run.** `monitor_db` adds about 1 s of `uv run genomics` subprocesses to
  `tests/test_pipeline.py`.
- **`deid_lacks_tier()` returning False on error** means that if the real file can't be opened,
  the real-DB tests run and fail with the underlying error instead of skipping. That's the
  intended trade: collection of the synthetic tests isn't affected, and the real failure stays
  visible. The guard does nothing once the real file has `tier`. A later PR can delete it.
- **`unified.sql` is a seam.** The change is one `WHEN` predicate in the Caris branch. The
  column set and the `UNION ALL BY NAME` shape stay the same.
