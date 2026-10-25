# Spec #56: follow-ups from the #36 review

Issue #56 lists three minor/nit findings from the #36 review (saved cohorts in Postgres) that were
not fixed before merge. All three are text: two doc edits and one code comment. This spec fixes all
three in one PR. No behaviour changes.

## Goal

1. **code-r0-1**: the Test plan in `docs/specs/36-saved-cohorts-in-postgres-versions.md` matches
   `tests/test_saved.py` as merged. Later issues copy these specs, so the plan should describe the
   code that exists.
2. **code-r0-2**: the rate limiter's `ponytail:` comment in `mcp/src/uccc_genomics_mcp/app.py` no
   longer points at the saved-cohorts work, which has shipped and deliberately kept the limiter
   in-process.
3. **security-r0-1**: the #36 spec's Risks section and ARCHITECTURE decision 7 record that
   `cohort_id` resolution is a cross-user existence oracle for definitions, and why that is
   accepted. The orchestrator decided this on the issue: accept and document. Users are campus-only,
   no patient data or counts are revealed, and a keyed hash would add another key file to manage.
   Revisit if the audience widens.

## Non-goals

- No code change apart from the one comment. `saved.get_version`, `GET /api/versions/{cohort_id}`,
  the MCP tool `get_cohort_version`, `cohort_id` computation (`cohort/definition.py`) and the rate
  limiter (`RATE_LIMIT`, `RATE_WINDOW`, `_calls`, `rate_limit`) are unchanged. No rate limit is
  added to version lookups.
- No change to `tests/test_saved.py` or any other test. The spec is edited to match the tests, not
  the other way round.
- No keyed `cohort_id` and no share link that carries the full definition. The issue lists both as
  alternatives, and the decision rejects them for now.
- `docs/specs/35-genomics-app-fastapi-rest-and-mcp-over.md:218` also says the limiter's upgrade path
  is "Postgres or Redis with the saved-cohorts work". It is the #35 record of what was planned then,
  so it stays. The #36 spec's Non-goals line about the comment ("its `ponytail:` comment still names
  Postgres or Redis as the upgrade path") stays true after this change and is not edited.
- No data change. Nothing touches `deid.py`, the de-id file, the mart or any output path, so no
  small-cell rule changes and **`research_id` and `report_id` stability is not affected**.
- No new dependencies.

## Design

Four files change: `mcp/src/uccc_genomics_mcp/app.py`, `docs/specs/36-saved-cohorts-in-postgres-versions.md`,
`docs/ARCHITECTURE.md` and this spec. Nothing under `src/uccc_genomics/`, `dashboard/`, `web/` or
`systemd/` changes.

### 1. `mcp/src/uccc_genomics_mcp/app.py` (code-r0-2)

Lines 135-136 today:

```python
# ponytail: in-process, per user, reset on restart; per-process limits multiply with more than one
# worker. Move to Postgres or Redis with the saved-cohorts work.
```

become:

```python
# ponytail: in-process, per user, reset on restart; per-process limits multiply with more than one
# worker. Move to Postgres (saved.py's database) or Redis when more than one worker runs.
```

Nothing else in the file changes.

### 2. `docs/specs/36-saved-cohorts-in-postgres-versions.md`, Test plan (code-r0-1)

Replace the "Fixtures:" list and the "Tests:" list of the `## Test plan` section (from the line
`Fixtures:` through test 11, `test_database_url`) with the text below. The opening paragraph, the
"`tests/test_app.py` changes" list and the "Run:" paragraph match the code already and stay as they
are.

```markdown
Fixtures and helpers:

- Imported from `tests/test_app.py`: the `mart_file` and `ids` fixtures (the synthetic #34 mart,
  `use_mart`, `app.get_db` on it, a fresh `app._calls`), plus `MCP_HEADERS` and `walk`.
- `pg_url` (module scope): `url = os.environ.get("TEST_DATABASE_URL")`; if unset,
  `pytest.skip("saved cohorts: set TEST_DATABASE_URL to a throwaway Postgres to run these (README)")`.
  If it equals `os.environ.get("DATABASE_URL")`, `pytest.fail` (the tests drop the schema). With
  `pytest.MonkeyPatch.context()` setting `DATABASE_URL=url`, run
  `command.downgrade(cfg, "base")`, `command.upgrade(cfg, "head")` and `command.check(cfg)`, where
  `cfg = alembic.config.Config(str(REPO / "mcp" / "alembic.ini"))`.
- `sql(statement, **params)`: runs one statement on a short-lived
  `create_async_engine(saved.database_url())` inside `asyncio.run` and returns the rows as dicts
  (an empty list when the statement returns none).
- `clean` (function scope, needs `pg_url`): `monkeypatch.setenv("DATABASE_URL", pg_url)`, then
  `sql("TRUNCATE snapshot, cohort_revision, cohort, cohort_version")`. Tests that call `saved.*`
  directly use `clean` alone.
- `sclient` (function scope, needs `ids` and `clean`): `monkeypatch.setattr(authen, "user", fake)`
  where `fake(request)` returns `request.headers["x-test-user"]` or raises `PermissionError`; then
  `with TestClient(app.app()) as c`, sets `c.ids = ids` and yields `c`.
- `Resp(code, body)`: a namedtuple. `code` is the HTTP status for REST; for MCP it is 200, or
  `None` when the result `isError` (then `body` is the error text).
- Class `Rest(c, user="a@x.edu")`: one method per saved-cohort call, each sending `x-test-user`:
  `save(d)`, `list()`, `get(id)`, `apply(id, op)`, `history(id)`, `revert(id, to)`, `snapshot(id)`,
  `delete(id)`, `snapshots()`, `version(cohort_id)` and `count(d)` (`POST /api/cohort`).
- Class `Mcp(Rest)`: the same methods as `tools/call` POSTs to `/mcp` (`save_cohort`,
  `list_saved_cohorts`, `get_saved_cohort`, `apply_saved_op`, `saved_cohort_history`,
  `revert_saved_cohort`, `snapshot_saved_cohort`, `delete_saved_cohort`, `list_snapshots`,
  `get_cohort_version`, `count`), returning `structuredContent` or the `isError` text. A test runs
  one script against either surface by passing a `Rest` or an `Mcp`.
- `mask(x)`: replaces every string matching a UUID or an ISO-8601 timestamp with `"*"`,
  recursively. `ok(r)`: asserts `r.code == 200` and returns `r.body`. `script(s)`: the parity
  script below, returning every response.

Tests:

1. `test_saved_parity`: one script, run once through `Rest` as user A and once through `Mcp` as
   user B (each surface creates its own cohort from `{"name": "x", "population": {"oncotree":
   ["NSCLC"]}}`; a second user because snapshots outlive their cohort): save; get; apply
   `add_criterion` KRAS G12C; apply `rename`; apply `set_breakdown ["sex"]`; revert to 1; history;
   snapshot; list snapshots; list; delete; list. Every step is 200, and
   `mask(rest_response) == mask(mcp_response)` at every step.
2. `test_saved_reads_are_identical`: create through REST, then get, history, list, list snapshots
   (after one snapshot) and version on both surfaces; exact equality.
3. `test_revisions`: the seq, `op`, `cohort_id` and name rules in the acceptance list.
4. `test_ownership`: the B-against-A matrix on both surfaces, A unchanged after; B resolves A's
   `cohort_id` and saves a copy, which gets its own id.
5. `test_cohort_version_is_content_addressed`: two users, same selecting definition, different
   names and breakdowns: one row, selecting part only, no `created_by` in the response; unknown
   `cohort_id` 404 / `isError`.
6. `test_snapshot`: result equals `POST /api/cohort` for the head; `data_date ==
   cohort.data_date()`; one audit line (`capsys`); a cohort under the floor still stores only
   suppressed values; with `app.RATE_LIMIT` at 1 and the budget spent, 429 / `isError` and the
   snapshot list is unchanged.
7. `test_nothing_small_or_identifying_stored`: after tests 1–6's kind of script, read every row of
   all four tables with `sql`; no `research_id`/`report_id` string from `ids`, no
   `patients`/`denominator`/`reports` keys outside `snapshot.result`, and no 1–4 under those keys
   anywhere.
8. `test_saved_errors_agree`, parametrized over `ERRORS`: unknown id (404, "no saved cohort"),
   malformed id (422 / `isError`, "uuid"), gene not in the vocabulary on save and on apply (400,
   "gene"), unknown op (422, "op"), revert to 99 (404, "no revision"). REST status and MCP
   `isError` text both name the problem.
9. `test_caps`: monkeypatch `saved.MAX_COHORTS` to 1, `MAX_REVISIONS` to 2 and `MAX_SNAPSHOTS` to
   1; the next save, apply, revert and snapshot are 409 over REST and `isError` over MCP. Caps are
   per user: user B can still save.
10. `test_stale_append_conflicts` (uses `clean`, no TestClient): inside one `asyncio.run`,
    `saved.start(saved.database_url())`, `create`, `append(..., after=1)` succeeds, `append(...,
    after=1)` again raises `Conflict`, `append` as another user raises `NotFound`, and
    `await saved.stop()` in a `finally`.
11. `test_delete`: get, history, apply and a second delete 404 afterwards; earlier snapshots and the
    `cohort_version` row remain, and `cohort_revision` is empty.
12. `test_database_url` (no Postgres needed, not using `pg_url`): unset → `None`;
    `postgresql://u:p@h:5432/d` → drivername `postgresql+asyncpg`, same host, port, database.
13. `test_data_date_is_a_date` (no Postgres needed, uses `ids`): `cohort.data_date()` returns a
    `datetime.date`.
```

### 3. `docs/specs/36-saved-cohorts-in-postgres-versions.md`, the `cohort_id` oracle (security-r0-1)

**"What leaves the host" section**, the Ownership bullet (today ending "so ids cannot be probed for
existence. Ids are random UUIDs."). Replace the bullet with:

```markdown
- Ownership: every read and write of `cohort`, `cohort_revision` and `snapshot` is filtered by the
  email `RequireUser` stored. Someone else's id gives the same 404 as a missing one, so saved-cohort
  ids cannot be probed for existence. Those ids are random UUIDs. `cohort_id` is different: see the
  `cohort_id` existence oracle under Risks.
```

**Risks section**: add this bullet directly after the "Ownership is the security boundary" bullet:

```markdown
- **`cohort_id` is a cross-user existence oracle for definitions (accepted, #56).** `cohort_id` is
  an unkeyed sha256 of the selecting definition, and the code that computes it is public. Any
  logged-in user can compute the id of a candidate definition and call `GET
  /api/versions/{cohort_id}` (or `get_cohort_version`). A 200 means some user has saved or
  snapshotted that definition; a 404 means nobody has. The lookup is not rate-limited. It reveals
  other users' research activity, not patient data: the response is the definition the caller
  already had, with no counts and no `created_by`. Accepted because users are campus-only, nothing
  about patients leaks, and a keyed `cohort_id` would add another key file to manage. Revisit if the
  audience widens beyond campus. The fixes then are a share link that carries the selecting
  definition itself (no server lookup), or a `cohort_id` computed with a server-side key (which
  changes every id the cohort module returns, so it needs its own issue).
```

### 4. `docs/ARCHITECTURE.md`, decision 7 (security-r0-1)

Decision 7 ends "Every read and write is scoped to the owner. The query audit log stays one JSON
line on stdout for now; moving it to Postgres is a later issue." Between those two sentences, add:

```markdown
The exception is `cohort_version`: any logged-in user can resolve a `cohort_id`, so the lookup
shows whether anyone has saved a given definition (an existence oracle). That is accepted: users
are campus-only and no patient data or counts are revealed, and a keyed `cohort_id` would mean
another key file to manage. Revisit if the audience widens (#56).
```

Keep the paragraph's existing 3-space hanging indent and wrap at the file's usual width (about 100
columns).

### What leaves the host

Nothing new. No endpoint, tool, page or loader changes, so the small-cell rule (floor 5, secondary
suppression, the whole-cohort rule) is unchanged everywhere. The docs now record an existing,
non-patient-data disclosure. `research_id` and `report_id` are not touched.

## Acceptance criteria

- [ ] `mcp/src/uccc_genomics_mcp/app.py`: the limiter comment reads "Move to Postgres (saved.py's
      database) or Redis when more than one worker runs." and `grep -n "saved-cohorts work"
      mcp/src` finds nothing. `git diff origin/main -- mcp/` shows only that comment line.
- [ ] Spec #36 Test plan names the `clean` and `sclient` fixtures (only `clean` truncates), the
      `sql` helper, the `Rest` / `Mcp` classes and `Resp`, and lists 13 tests whose names are
      exactly the `def test_*` names in `tests/test_saved.py`. Check: every name from
      `grep -o "def test_[a-z_]*" tests/test_saved.py` appears in the spec's Test plan, and the
      spec no longer contains `test_errors_agree`, `test_caps_and_conflict`, `rest(c,` or
      `tool(c,`.
- [ ] Spec #36 Risks has the `cohort_id` existence-oracle bullet (accepted, why, when to revisit,
      the two alternatives), and its Ownership bullet scopes "cannot be probed for existence" to
      saved-cohort ids and points at that bullet.
- [ ] `docs/ARCHITECTURE.md` decision 7 states the `cohort_version` exception and that it is
      accepted, with the reason and the revisit condition.
- [ ] No test file, no other code, no SQL and nothing under `dashboard/`, `web/`, `systemd/` or
      `src/uccc_genomics/` changes.
- [ ] `uv run pytest -q` passes (Postgres tests skip without `TEST_DATABASE_URL`).

## Test plan

No test is added: the change is two doc edits and one comment, and no behaviour changes.

- `uv run pytest -q`: must pass as before, which shows the comment edit broke nothing.
- The grep checks in the acceptance list (the comment text, the test names in spec #36, the
  removed names).
- Dashboard check: n/a (nothing under `dashboard/` changes). Web check: n/a (nothing under `web/`
  and no API model changes).
- No synthetic data, `$DATA`, PHI file or Postgres is needed. The edited text uses column names and
  synthetic definitions only, no real counts, values or identifiers.

## Risks

- **The spec drifts from the tests again.** Copying test names by hand can go stale with the next
  test edit. The acceptance grep catches it for this PR only. Later changes to `tests/test_saved.py`
  should update spec #36 in the same PR, or say that it is a historical record.
- **Accepting the oracle is a decision with a condition.** It holds while the audience is campus
  users behind authentication. If `genomics-app` is opened wider (other institutions, a public demo),
  the Risks bullet and decision 7 both name this for revisiting. The fix then is a separate issue.
