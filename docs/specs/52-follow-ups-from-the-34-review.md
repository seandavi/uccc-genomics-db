# Spec #52: follow-ups from the #34 review

Issue #52 collects three findings from the #34 review that were left open at merge:

- **code-r0-5** (minor): `test_floor` depends on the host's `COHORT_ROUND`.
- **security-r0-6** (nit): `ID_RE` and `AXIS_RE` accept a trailing newline.
- **code-r1-2** (minor): the `loosen[]` row in the COHORT_DISCOVERY.md §3.6 privacy table
  leaves out the delta checks.

Each is a small edit. The spec pins the exact change for each one, so the implementer has
nothing to choose.

## Goal

1. The test suite passes on a host whose `.env` sets `COHORT_ROUND=5`, the option
   `dashboard/COHORT_TOOL.md` documents. Today `COHORT_ROUND=5 uv run pytest -q` fails 6 tests:
   `test_cohort.py::test_floor` and 5 tests in `test_cohort_api.py`
   (`test_counts_patients_not_reports`, `test_prevalence_denominator_and_or_within_a_parameter`,
   `test_whole_cohort_rule`, `test_vus_is_excluded_unless_asked`,
   `test_unclassified_is_opt_in`). I checked this in this worktree. The issue names only
   `test_floor`, but the 5 `test_cohort_api.py` tests fail for the same reason: `cohort_api`
   calls `suppress.floor`, which reads `suppress.ROUND`, and the `client` fixture doesn't pin
   it. Both get the same one-line fix.
2. A criterion id or a pivot axis with a trailing newline (`"c1\n"`, `"c1.key\n"`) is
   rejected with the same `DefinitionError` as any other malformed id or axis. That covers
   `Definition` validation and `compile._axis`.
3. The §3.6 privacy table states the `loosen[]` control the way §3.3 and #34's suppression rule
   6 / spec item 12 already state it.

## Non-goals

- No change to `suppress.py`, `ROUND`, `MIN_CELL`, `floor`, or any suppression rule. Nothing new
  leaves the de-id file, so no new small-cell rule applies. Goal 2 narrows what the validator
  on the seam accepts. Goal 3 is a doc correction.
- No change to `deid.py`, `sql/`, `src/uccc_genomics/`, `dashboard/` code, `web/` or `systemd/`.
  **`research_id` and `report_id` are unaffected.** Nothing here touches the de-id build.
- No change to `cohort_id` for any definition that validates today and has no trailing newline.
  Ids and axes that validate today are byte-for-byte what they were, so their hashes stay the
  same. A saved cohort whose definition holds an id like `"c1\n"` would now fail to parse. Such
  a definition can only come from a hand-written API call (Discover and `apply` generate
  `c<n>` ids), so the risk is accepted rather than migrated (see Risks).
- No conftest-wide autouse fixture for `ROUND`. The two fixtures that need it (`use_mart` in
  `test_cohort.py`, which `cohort_db` calls, and `client` in `test_cohort_api.py`) and
  `test_floor` set it directly, which is the pattern already in place.
- No edit to past specs. `docs/specs/34-cohort-module-definition-operations.md` lines 286 and
  290 quote the regexes with `$`. That spec is the record of #34 and stays as it was. The code
  is the source of truth.
- No new dependency.

## Design

### `mcp/src/uccc_genomics_mcp/cohort/definition.py` (security-r0-6)

Change the end anchor in the two module-level regexes from `$` to `\Z`. Nothing else changes.

```python
ID_RE = re.compile(r"^c[1-9][0-9]{0,2}\Z")
AXIS_RE = re.compile(r"^(c[1-9][0-9]{0,2})\.(key|sub|val)\Z")
```

Fix it at the definition and leave the call sites alone. All three callers route through these
two patterns with `.match`: `Definition._check` (line 301, `ID_RE.match`),
`Definition._check_pivot` (line 321, `AXIS_RE.match`) and `compile._axis` (`compile.py` line 174,
`AXIS_RE.match`). In Python `re`, `\Z` matches only at the very end of the string, while `$`
also matches before one trailing `\n`. I checked this with Python 3.12 in this worktree:

| input | `$` (today) | `\Z` |
|---|---|---|
| `"c1"` | match | match |
| `"c1\n"` | match | no match |
| `"c12"` | match | match |
| `"c1.key"` | match (axis) | match (axis) |
| `"c1.key\n"` | match (axis) | no match (axis) |

Error paths after the change, with no new messages:

- `parse({"criteria": [{..., "id": "c1\n"}]})` raises `DefinitionError` matching
  `"needs an id"` (from `_check`).
- `parse({..., "pivot": {"rows": "oncotree", "cols": "c1.key\n"}})` raises `DefinitionError`
  matching `"not a dimension"`. `AXIS_RE` doesn't match, `"c1.key\n"` isn't in `PIVOT_DIMS`, so
  `_check_pivot` gives its "is not a dimension or a criterion axis" error.
- `compile_pivot` on a definition whose `pivot` was built with
  `Pivot.model_construct(rows="c1.key\n", cols="year")` raises `DefinitionError` matching
  `"not a pivot axis"` (from `_axis`).

### `tests/test_cohort.py`

1. **code-r0-5.** `test_floor` takes `monkeypatch` and pins `ROUND` before asserting, as
   `use_mart` does:

   ```python
   def test_floor(monkeypatch):
       monkeypatch.setattr(suppress, "ROUND", 1)
       assert [floor(n) for n in (None, 0, 1, 4, 5, 6)] == [None, 0, None, None, 5, 6]
   ```

   `floor` reads the module global `ROUND` at call time (`suppress.py` line 27), so patching
   `suppress.ROUND` is enough. `suppress` is already imported in this file.

2. **security-r0-6.** Add two cases to the list in `test_static_validation_definition_level`,
   right after the existing `"needs an id"` and `"not a dimension"` entries:

   ```python
   ({"criteria": [{**a, "id": "c1\n"}]}, "needs an id"),
   ({"criteria": [a], "pivot": {"rows": "oncotree", "cols": "c1.key\n"}}, "not a dimension"),
   ```

   Add one assertion to `test_compile_validates_names_it_puts_in_the_sql`, after the `"c9.key"`
   case:

   ```python
   with pytest.raises(DefinitionError, match="not a pivot axis"):
       compile_pivot(d.model_copy(update={"pivot": Pivot.model_construct(rows="c1.key\n", cols="year")}))
   ```

   All three fail on today's `$` anchors. The two `parse` cases are accepted and raise nothing.
   In the `compile_pivot` case `AXIS_RE.match` succeeds and `_axis` returns `("fact", "key", 0)`,
   so `pytest.raises` fails.

### `tests/test_cohort_api.py` (code-r0-5, same root cause)

In the `client` fixture, add one line after the existing `monkeypatch.setattr` calls:

```python
monkeypatch.setattr(suppress, "ROUND", 1)
```

Add `from uccc_genomics_mcp.cohort import suppress` to the imports, next to the existing
`from uccc_genomics_mcp import authen, cohort_api, server`. `cohort_api` imports `floor` from
`suppress` by name, but `floor` reads `suppress.ROUND` from its own module globals, so patching
the `suppress` module attribute takes effect. `test_real_db_matches_hand_written_sql` doesn't use
`client` and is unchanged.

### `dashboard/COHORT_DISCOVERY.md` (code-r1-2)

In the §3.6 privacy table, replace the Control cell of the `` `loosen[]` suggestions `` row:

```
| `loosen[]` suggestions | Each suggestion is itself a count. | Each one is an ordinary floored cohort query and is logged like any other. |
```

with:

```
| `loosen[]` suggestions | Each suggestion is itself a count. | Floored; shown only if at least 5 above the current cohort's raw count, not 1 to 4 from a shown funnel step and not equal to a hidden one (§3.3); logged with the `count` request that computed it. |
```

The wording follows the §3.3 bullet ("A suggestion is shown only if its count is at least 5, at
least 5 above the current cohort's raw count, and not 1 to 4 away from a shown funnel step or
equal to a hidden one") and `suppress.suppress_count`, which keeps a suggestion only if
`floor(L)` is not `None`. "Logged with the `count` request" replaces "logged like any other"
because loosen counts are not audited one by one. `app.audit` writes one line per `count` call,
and that call is the one that computed the suggestions. No other line of COHORT_DISCOVERY.md,
ARCHITECTURE.md, COHORT_TOOL.md, README.md or PLAN.md changes. None of them restate this
control.

## Acceptance criteria

- [ ] `definition.py` has `ID_RE = re.compile(r"^c[1-9][0-9]{0,2}\Z")` and
      `AXIS_RE = re.compile(r"^(c[1-9][0-9]{0,2})\.(key|sub|val)\Z")`. No call site changes.
- [ ] `parse` rejects criterion id `"c1\n"` ("needs an id") and pivot axis `"c1.key\n"` ("not a
      dimension"). `compile_pivot` rejects a `model_construct`ed pivot axis `"c1.key\n"` ("not a
      pivot axis"). Each case is pinned by the tests above and fails if the anchors go back to
      `$`.
- [ ] `test_floor` takes `monkeypatch` and sets `suppress.ROUND = 1`. The `client` fixture in
      `tests/test_cohort_api.py` does the same.
- [ ] `COHORT_ROUND=5 uv run pytest -q` passes, with the same pass/skip counts as a plain
      `uv run pytest -q`.
- [ ] `uv run pytest -q` passes.
- [ ] The COHORT_DISCOVERY.md §3.6 `loosen[]` Control cell reads exactly as in Design.
- [ ] No change outside `mcp/src/uccc_genomics_mcp/cohort/definition.py`,
      `tests/test_cohort.py`, `tests/test_cohort_api.py` and `dashboard/COHORT_DISCOVERY.md`.

## Test plan

- `uv run pytest -q`. Tests build synthetic marts and DuckDB files under `tmp_path`. Nothing
  reads `$DATA/raw/` or the PHI file.
- `COHORT_ROUND=5 uv run pytest -q`. The environment variable overrides the repo `.env`
  (`load_dotenv` doesn't override variables that are already set), so this reproduces the host
  the issue describes. Before the change it reports 6 failures. After it, it should report
  none.
- Regression check in a scratch copy, never committed: put the `$` anchors back. The two new
  `test_static_validation_definition_level` cases and the new `compile_pivot` assertion fail.
- Dashboard check (`cd dashboard && npm ci && npm test`): n/a. Only a Markdown file under
  `dashboard/` changes.
- Web check (`cd web && bun install --frozen-lockfile && bun run typecheck && bun test`): n/a.
  Nothing under `web/` changes and the API models are unchanged (the regexes don't appear in
  `openapi.json` or the JSON Schemas).

## Risks

- **A stored definition with a newline-suffixed id stops parsing.** A saved cohort revision
  written through a hand-made REST or MCP call with id `"c1\n"` would now raise
  `DefinitionError` when it is read back. Discover and `apply` only produce `c<n>` ids, so no
  normal path writes one. Saved cohorts live in a Postgres store that is still new, and the fix
  is the reason for the change: `"c1"` and `"c1\n"` must not coexist as distinct ids.
- **Other `ROUND`-dependent tests added later** have to pin `ROUND` themselves, as these
  fixtures do. A conftest autouse fixture would cover that, and it is left out on purpose (see
  Non-goals).
