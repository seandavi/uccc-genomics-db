# Spec #45: follow-ups from the #33 review

Issue #45 lists three minor findings from the #33 review that weren't fixed before merge. This
spec fixes all three in one PR. Two only add fixtures and assertions to `tests/test_pipeline.py`.
The third changes the de-identification leak assert in `deid.py`.

While writing this spec I found a larger defect behind security-r0-1. The leak assert uses
DuckDB's `~` operator, and in DuckDB `~` is a **full** match (`regexp_full_match`), not the
substring match it is in PostgreSQL. I checked this in duckdb 1.5.5:
`'x ORD-0001234-01 y' ~ 'ORD-[0-9]{6,}'` is false, and `'ORD-0001234' ~ 'ORD-[0-9]{6,}'` is true.
So today the assert only flags a value that is nothing but an identifier. An id inside prose
(an `interpretation` column, for example) gets through. The synthetic FMI fixture already has one
(`<Interpretation>TP53 R175H ... ORD-0001234-01 was reviewed.</Interpretation>`), and
`test_phi_columns_are_gone_and_ids_are_hashed` hides it with `... or True`. DuckDB has no `~*`, so
the issue's case-insensitive option can't be done with `~` either. This spec switches the match
to `regexp_matches(..., 'i')`, which is a substring match that ignores case. That is what both the
issue and the docstring ("no vendor accession / sample id may survive in any text column") assume.

## Goal

1. **code-r0-2**: a test fails if either source of `mart.report.has_wts` is removed from the
   `wts` CTE in `mart.sql`, or if its `assay IN ('RNA', 'cfTNA')` filter is dropped or narrowed.
2. **security-r0-1**: the leak assert also scans `mart.*`, matches `ID_PATTERN` as a substring
   anywhere in a value, and ignores case. A test in `tests/test_pipeline.py` pins all three.
3. **code-r1-1**: a fixture reaches the unit-nulling `CASE` in `mart.fact` (a Caris PD-L1
   record with no score), and the tests assert its fact row.

## Non-goals

- No change to `ID_PATTERN`, the PHI `DROP` / `HASH` sets, id hashing, date shifting or age
  capping. `research_id` and `report_id` are computed exactly as before, so they stay stable for
  the same key and the same patient.
- No change to `mart.sql`, `unified.sql`, the vendor loaders, the cohort API, the dashboard
  loader or MCP tools.
- No redaction of identifiers inside free text. If a real text column ever contains one, the
  assert fails the rebuild, as the design intends. Scrubbing would be a separate decision.
- No change to how `deid.run()` writes the file (in place, then asserts). See Risks.
- No new dependencies.

## Design

### 1. `src/uccc_genomics/deid.py`: leak assert (security-r0-1)

Move the leak loop out of `run()` into a module-level function so a test can call it on a small
synthetic DuckDB:

```python
def find_leaks(con, schemas):
    """`schema.table.column: n` for every VARCHAR/JSON column in `schemas` of the current catalog
    with a value containing an ID_PATTERN token, ignoring case (mart.sql lower()s some values)."""
    leaks = []
    for s in schemas:
        for t, c in con.execute(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_catalog=current_database() "
                "AND table_schema=? AND data_type IN ('VARCHAR','JSON')", [s]).fetchall():
            # regexp_matches is a substring match; DuckDB's `~` is a full match and would miss embedded ids
            n = con.execute(f'SELECT count(*) FROM {s}."{t}" WHERE regexp_matches("{c}"::VARCHAR, ?, \'i\')',
                            [ID_PATTERN]).fetchone()[0]
            if n:
                leaks.append(f"{s}.{t}.{c}: {n}")
    return leaks
```

`find_leaks` goes right after `ID_PATTERN`, before `run()`. In `run()`, the loop is replaced by:

```python
    # ponytail: leak check — no vendor accession / sample id may survive in any text column
    leaks = find_leaks(con, [*present, "mart"])
    assert not leaks, "identifier-like tokens survived de-identification: " + "; ".join(leaks)
```

Notes:

- `regexp_matches(string, pattern, options)` with option `'i'` is DuckDB's case-insensitive
  partial match (RE2). I checked it in duckdb 1.5.5:
  `regexp_matches('x ord-0001234 y', 'ORD-[0-9]{6,}', 'i')` is true. The pattern stays a bound
  parameter, as it is today.
- The column query is unchanged. As before, it lists views as well as tables (for example
  `caris.wts_expression`). For `mart` it lists `mart.report` and `mart.fact`.
- `unified.*` isn't added. Those are views over the vendor tables that are already scanned, and
  `mart` is what later issues extend.
- Before writing this spec I ran the new predicate read-only against the real de-id file, over
  every VARCHAR/JSON column in `caris`, `fmi` and `mart` except `caris.gene_tpm`. No column
  matched, either as a substring or ignoring case, so the next daily rebuild shouldn't start
  failing on current data. `caris.gene_tpm`'s text columns are the hashed `case_id`, `assay` and
  `gene`, and the rebuild scans them as before.
- Update the module docstring by adding one line: "Fails (assert) if any text column in the
  vendor or mart schemas still contains an ID_PATTERN token, in any case."

### 2. `tests/test_pipeline.py`: fixtures and tests

All values are synthetic. Every pipeline run uses a pytest temp `DATA` dir.

**2a. The FMI interpretation fixture (needed by 1).** In `FMI`, change
`<Interpretation>TP53 R175H ... ORD-0001234-01 was reviewed.</Interpretation>` to
`<Interpretation>TP53 R175H was reviewed.</Interpretation>`. With the substring match, the old
text makes `genomics deid` fail on purpose (I checked this in a scratch copy: the `db` fixture
errors with `CalledProcessError` from `deid`). In `test_phi_columns_are_gone_and_ids_are_hashed`,
delete the line
`assert "ORD-" not in one(db, "SELECT interpretation FROM db.fmi.alteration")[0] or True  # leak assert in deid already ran`.
It never asserted anything, and `test_find_leaks_matches_embedded_and_lower_case_ids` replaces it.

**2b. `find_leaks` test (security-r0-1).**

```python
def test_find_leaks_matches_embedded_and_lower_case_ids():
    from uccc_genomics.deid import find_leaks
    con = duckdb.connect()
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.fact AS SELECT * FROM (VALUES ('trastuzumab', 'see tn26-123456 notes'), "
                "('olaparib', NULL), ('x', 'ORD-0001234-01')) t(val, note)")
    assert find_leaks(con, ["mart"]) == ["mart.fact.note: 2"]
    assert find_leaks(con, ["caris"]) == []
```

The first value is a lower-case id inside text, and the third is an id with a suffix. Neither
matches with `~`, so this test fails against the old predicate. I checked that in scratch too.
`run()` passing `"mart"` is the one-line call in §1. Going through the pipeline can't reach it,
because every mart text value is copied from a vendor column that is scanned first.

**2c. `has_wts` per source (code-r0-2).** The main `db` fixture models one Caris case with both
an RNA TPM file and a `wtsExpression` record, and many tests rely on its patient and report
counts. So the per-source cases get their own pipeline run, as `monitor_db` did in #43.

- Add `import copy` to the imports.
- Add a module constant and a helper after `FMI_MONITOR`:

  ```python
  # (case id, specimenSite, gene TPM file assays, has a wtsExpression record, has_wts): one Caris case per
  # has_wts source, so dropping either arm of mart.sql's `wts` CTE, or its assay filter, fails a case.
  WTS_CASES = [
      ("TN26-200001", "Liver", ["RNA"], False, True),
      ("TN26-200002", "Lung", ["cfTNA"], False, True),
      ("TN26-200003", "Colon", [], True, True),
      ("TN26-200004", "Brain", ["gDNA"], False, False),
  ]


  def caris_case(case_id, site, wts_expression):
      """CARIS as another patient's case `case_id` at `site`, keeping or dropping its wtsExpression record."""
      c = copy.deepcopy(CARIS)
      c["testDetails"]["labReportID"] = case_id
      c["patientInformation"]["mrn"] = "000" + case_id[-6:]
      spec = c["specimenInformation"]["tumorSpecimenInformation"]
      spec["specimenID"], spec["specimenSite"] = f"{case_id}-A", site
      if not wts_expression:
          c["tests"][0]["testResults"] = [r for r in c["tests"][0]["testResults"] if "wtsExpression" not in r]
      return c
  ```

  The site is the label: it reaches `mart.report.site` as `lower(trim(specimenSite))`, while
  `report_id` is hashed. The assay prefix of the TPM file name becomes `caris.gene_tpm.assay`
  through `regexp_extract(filename, '/([A-Za-z]+)_TN', 1)` in `caris.load()`.

- `pipeline()` gets an optional third parameter. The Caris writes move into a loop. The `db` and
  `monitor_db` calls don't change, and with the default they write exactly the files they write
  today:

  ```python
  def pipeline(data, fmi_files, caris_cases=None):
      """Write `caris_cases` ({case id: (report JSON, gene TPM file assays)}, default CARIS with an RNA
      TPM file) and `fmi_files` ({file name: XML text}) under raw/ in `data`, run load for both vendors
      and deid, and return a connection with the de-id file attached as `db` and the PHI file as `phi`,
      both read-only."""
      os.makedirs(f"{data}/raw/fmi")
      for case_id, (report, assays) in (caris_cases or {"TN26-123456": (CARIS, ["RNA"])}).items():
          case = f"{data}/raw/caris/{case_id}"
          os.makedirs(case)
          json.dump(report, open(f"{case}/{case_id}.json", "w"))
          for assay in assays:
              with open(f"{case}/{assay}_{case_id}_geneTPM_nodup.csv", "w", newline="") as f:
                  w = csv.writer(f)
                  w.writerow(["Gene", "TPM", "NumReads"])
                  w.writerows([["TP53", "12.5", "800"], ["ERBB2", "300.1", "9000"]])
      # ... FMI writes, load, deid, ATTACH: unchanged
  ```

- New fixture (after `monitor_db`) and test (before `test_mart_fact_keys_and_kinds`).
  `FMI_MONITOR` is reused only because `load --vendor fmi` needs one FMI file:

  ```python
  @pytest.fixture(scope="module")
  def wts_db(tmp_path_factory):
      return pipeline(str(tmp_path_factory.mktemp("wts")), {"ORD-0005678-01.xml": FMI_MONITOR},
                      {c: (caris_case(c, site, wts), assays) for c, site, assays, wts, _ in WTS_CASES})


  def test_mart_report_has_wts_per_source(wts_db):
      """RNA and cfTNA TPM files and wtsExpression records each make has_wts true on their own; a gDNA TPM file doesn't."""
      got = dict(wts_db.execute("SELECT site, has_wts FROM db.mart.report WHERE vendor = 'caris'").fetchall())
      assert got == {site.lower(): want for _, site, _, _, want in WTS_CASES}
  ```

  In scratch, I edited `mart.sql` four ways, one at a time. Each edit made this test fail, and
  the test passes against `mart.sql` as merged:

  | edit to `wts` CTE | case that fails |
  |---|---|
  | drop `WHERE assay IN ('RNA', 'cfTNA')` | Brain (gDNA → true) |
  | `assay IN ('RNA')` only | Lung (cfTNA → false) |
  | drop the `caris.wts_expression` arm | Colon (→ false) |
  | drop the `caris.gene_tpm` arm | Liver, Lung (→ false) |

  Each case has its own MRN, so each one is its own patient. The `nopid` path isn't used. `deid`
  and the new leak assert pass on this run, because the case ids reach only the hashed
  `case_id` and the hashed `specimen_id`.

**2d. PD-L1 with no score (code-r1-1).** In `CARIS` `testResults`, right after the second
`PD-L1 (22c3)` record (the `cpScore` one), add:

```python
                   # no score: value NULL while unified.biomarker.unit is '% stained', so mart.fact must null the unit
                   {"expressionAlteration": {"biomarkerName": "PD-L1 (SP142)", "result": "Positive", "expressionType": "IHC"}},
```

The PD-L1 arm of `unified.biomarker` gives `value = coalesce(tps, cps, stain_pct)` = NULL,
`unit = '% stained'` (the `ELSE` branch) and `clone = 'sp142'`. The `mart.fact` CASE then sets
`unit` to NULL. Its result is 'Positive', so `call_norm` is 'positive', and the
`test_unified_views` dict keyed on (vendor, name) still maps `("caris", "PD-L1")` to
`"positive"`. In `test_mart_fact_ihc`:

- add `("PD-L1", "sp142", "positive", None, None)` to the expected subset;
- change the clone assertion to
  `{r[0] for r in db.execute("SELECT clone FROM db.unified.biomarker WHERE name = 'PD-L1'").fetchall()} == {"22c3", "sp142"}`.

If the CASE is replaced by plain `unit`, both `test_mart_fact_keys_and_kinds`
(`num IS NULL AND unit IS NOT NULL` = 0) and `test_mart_fact_ihc` fail. I checked that in scratch.

### 3. Docs

- `docs/specs/33-mart-schema-mart-report-and-mart-fact.md`, the paragraph under `deid.py`:
  replace "The leak assert keeps scanning the vendor schemas only. Every text value in `mart.*`
  is copied from a column it already scanned (or from `reference.disease_crosswalk`, which ships
  in the package), so the mart adds no new text source." with "The leak assert scans the vendor
  schemas and `mart.*`, as a case-insensitive substring match (#45). Every text value in `mart.*`
  is copied from a column it already scanned (or from `reference.disease_crosswalk`, which ships
  in the package), so the mart scan is defense in depth, in case a later arm adds a new text
  source."
- No change to README.md, AGENTS.md, PLAN.md, ARCHITECTURE.md or COHORT_DISCOVERY.md. They
  mention the leak assert only by name, and this change makes it do what they already describe.

### What leaves the de-id file

Nothing new. No loader, endpoint, MCP tool or export is added or changed, and no table, column
or value in the de-id file changes. The cohort API, dashboard loader (`MIN_CELL = 5`) and MCP
server keep their existing small-cell rules. The only behavior change makes the gate on what
gets written stricter: `deid` now refuses to finish in cases where it used to pass.

## Acceptance criteria

- [ ] `deid.find_leaks(con, schemas)` exists as in Design §1 and uses
      `regexp_matches(col::VARCHAR, ?, 'i')` with `ID_PATTERN` bound. `run()` calls it with
      `[*present, "mart"]` and asserts that the result is empty, with the same message as before.
- [ ] `ID_PATTERN`, `DROP`, `HASH`, `KEY_COL`, `IDENTITY` and the `xw` hashing/shift SQL are
      unchanged (`git diff src/uccc_genomics/deid.py` touches only the docstring, the new function
      and the leak block in `run()`).
- [ ] `test_find_leaks_matches_embedded_and_lower_case_ids` passes, and fails if the predicate
      goes back to `~ ?`.
- [ ] The `FMI` interpretation has no `ORD-` id, and the `... or True` line is gone.
- [ ] `test_mart_report_has_wts_per_source` passes against the merged `mart.sql` and fails under
      each of the four edits in the Design §2c table.
- [ ] The `PD-L1 (SP142)` no-score record is in `CARIS`. `test_mart_fact_ihc` asserts
      `("PD-L1", "sp142", "positive", None, None)` and clones `{"22c3", "sp142"}`, and fails if
      the `mart.fact` unit CASE is replaced by `unit`.
- [ ] The `db` and `monitor_db` fixtures write the same raw files as before (apart from the
      interpretation text and the new PD-L1 record), and every other pre-existing assertion in
      `tests/test_pipeline.py` passes unmodified. That includes the id and date-shift assertions.
- [ ] The spec #33 sentence is updated as in Design §3.
- [ ] `uv run pytest -q` passes. The dashboard check is n/a (no dashboard change), though
      `cd dashboard && npm ci && npm test` should still pass.

## Test plan

Everything is synthetic and built in pytest temp dirs (synthetic Caris JSON and FMI XML →
`genomics load` → `genomics deid` under a temp `DATA`). One test uses an in-memory DuckDB.
Nothing reads `$DATA/raw` or the PHI file.

- `tests/test_pipeline.py`:
  - `test_find_leaks_matches_embedded_and_lower_case_ids` (new, in-memory DuckDB, §2b).
  - `test_mart_report_has_wts_per_source` (new, `wts_db` fixture, §2c).
  - `test_mart_fact_ihc` (updated, §2d). `test_mart_fact_keys_and_kinds` (unchanged) now has a
    row that exercises its `num IS NULL AND unit IS NOT NULL` check.
  - `test_phi_columns_are_gone_and_ids_are_hashed`: the no-op line is removed (§2a). Every
    pipeline fixture (`db`, `monitor_db`, `wts_db`) runs the new leak assert through `genomics deid`.
- Regression checks for the implementer, in a scratch copy and never committed: revert the
  predicate to `~ ?` (the find_leaks test fails); put the old FMI interpretation back (`deid`
  fails, so the `db` fixture errors); apply each §2c edit to `mart.sql` (the has_wts test fails);
  replace the unit CASE with `unit` (the IHC and keys tests fail). I ran all of these while
  writing this spec. With the full change applied, `uv run pytest -q` reported 65 passed and 3
  skipped, and `tests/test_pipeline.py` took about 3 s.
- Real-DB checks (pipeline host, read-only, run by pytest): `test_real_db_matches_hand_written_sql`
  and `tests/test_dashboard_loaders.py` behave as they do today. Nothing in this change alters
  the real file until the daily rebuild, and that rebuild only adds the stricter assert.

## Risks

- **The daily rebuild can now fail on the leak assert.** Before, it could only fail on a value
  that was entirely an identifier. Now any embedded id fails it, in any case. The current real
  de-id file has no such value (checked read-only, as described in Design §1). A future vendor
  text field could add one. Then `genomics all` fails, `OnFailure=ntfy-notify` fires, and the
  dashboard build and deploy steps in `genomics.service` don't run. That's the intended
  fail-closed behavior.
- **A failed assert still leaves the rewritten de-id file on disk.** This is pre-existing and not
  changed here. `run()` removes and rewrites `genomics.duckdb` in place before it asserts, so
  after a failure the MCP server and the cohort API read a file that contains the flagged value
  until the next good rebuild. This spec makes that path more likely to be taken. Building into a
  temp path and renaming after the assert would fix it. That changes the shared `deid` seam, so
  it should be a separate issue.
- **False positives.** Ignoring case widens `ID_PATTERN` to strings such as `tn26-12345` or
  `ord-123456` in free text. That is the point: `mart.sql` lowercases some values. If a
  legitimate vendor term ever matches, the fix is a narrower `ID_PATTERN`, made in its own PR.
- **Rebuild time.** `regexp_matches` costs about the same per value as `~`. The extra `mart`
  scan reads `mart.report` and `mart.fact` once each.
- **Extra pipeline run.** `wts_db` adds one more `uv run genomics` load + deid cycle to
  `tests/test_pipeline.py`. The whole file still runs in a few seconds.
