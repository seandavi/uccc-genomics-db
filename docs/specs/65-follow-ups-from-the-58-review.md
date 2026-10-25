# Spec #65: follow-ups from the #58 review

Issue #65 lists the minor/nit findings from the #58 review (Discover follow-ups) that were not
fixed before merge, plus findings folded in from the #60 and #63 reviews in its one comment. This
spec fixes all of them in one PR, except **code-r0-2** of the issue body (the `search_vocabulary`
docstring), which the #66 merge already fixed on `main`. Its optional test is added here. Three
changes alter visible behaviour: the pivot legend sentence, the answer dimming and the wording of
the MCP instructions. Everything else is doc text or wrapping.

## Goal

From the issue body (#58 review):

1. **code-r0-1 / ux-r0-1**: the pivot legend no longer talks about blank cells. An omitted
   `(row, col)` pair renders `<td>0</td>`, so the table has no blank cells. The legend says what `0`
   and `<5` mean. Spec #58 changes to match.
2. **code-r0-2 / ux-r0-3**: already fixed on `main` (the `search_vocabulary` docstring lists every
   name in `FIELDS`). `test_tools_list` gains the optional assertion that pins it.
3. **code-r0-3 / ux-r0-4**: the "`localStorage` versions" Risks bullet in spec #37 ends with a
   sentence about that risk, not the share-link sentence. Spec #58 §Docs changes to match.
4. **code-r0-4**: the web tests pin that the breakdown tables and the pivot caption take labels from
   `answer.d` when it trails `definition`.
5. **code-r0-5**: the §3.3 doc-update item in spec #37 has no garbled `cohorts.);` punctuation.
6. **ux-r0-2**: after a failed count the answer is readable. The body is dimmed only while a count
   is in flight (`busy`), not while it is stale. Spec #58 changes to match.

From the issue comment (#60 and #63 reviews):

7. **security-r0-1**: the `cohort_id` existence-oracle text in spec #36, spec #56 and
   ARCHITECTURE decision 7 says that a 200 reflects past activity: version rows are never deleted.
8. **code-r0-1** (#60): the README "Cohort app (genomics-app)" paragraph is wrapped to the README's
   usual width (about 100 columns).
9. **code-r0-2 / ux-r1-1** (#60): the `INSTRUCTIONS` fragments in `app.py` are wrapped to about 110
   characters each.
10. **ux-r0-2** (#60): the README's example of a rejected request that still uses the rate limit is
    one that really reaches the cohort module: an unknown vocabulary value, or a pivot of a
    definition that has no pivot. Spec #54's README bullet changes to match.
11. **ux-r0-3** (#60): `INSTRUCTIONS` and the MCP `count` docstring say which reports `reports`
    counts.

## Non-goals

- No change to the cohort module, SQL, suppression, the rate limiter or any REST model. The REST
  OpenAPI schema does not change: `INSTRUCTIONS` and the MCP tool docstrings are not part of it.
  So `web/openapi.json` and `web/src/api.gen.ts` are not regenerated.
- No change to the `search_vocabulary` docstring (#66 fixed it).
- `.dim`'s opacity (`.55`) and its transition stay as they are. The issue's optional
  `prefers-reduced-motion` override is not added: the transition is a 0.15 s opacity fade, not
  motion.
- `dashboard/COHORT_DISCOVERY.md` §3.3 already has the correct punctuation and is not edited. Its
  "Phase 1 (#37)" paragraph has one overlong line, but no finding names it, so it stays.
- Spec #54's acceptance list still quotes `"reports counts reports"`. It is the record of what #54
  checked, so it stays. Only its README bullet changes, as the finding asks.
- No data change. Nothing touches `deid.py`, the de-id file, the mart or any output path, so no
  small-cell rule changes and **`research_id` and `report_id` stability is not affected**.
- No new dependencies.

## Design

Files that change:

| File | Findings |
|---|---|
| `web/src/Answer.tsx` | code-r0-1, ux-r0-2 |
| `web/src/answer.test.tsx` | code-r0-1, code-r0-4, ux-r0-2 |
| `mcp/src/uccc_genomics_mcp/app.py` | (#60) code-r0-2, ux-r0-3 |
| `tests/test_app.py` | (#58) code-r0-2, (#60) ux-r0-3 |
| `README.md` | (#60) code-r0-1, ux-r0-2 |
| `docs/ARCHITECTURE.md` | security-r0-1 |
| `docs/specs/36-saved-cohorts-in-postgres-versions.md` | security-r0-1 |
| `docs/specs/37-discover-react-app-for-building-cohorts.md` | code-r0-3, code-r0-5 |
| `docs/specs/54-follow-ups-from-the-35-review.md` | (#60) ux-r0-2 |
| `docs/specs/56-follow-ups-from-the-36-review.md` | security-r0-1 |
| `docs/specs/58-follow-ups-from-the-37-review.md` | code-r0-1, code-r0-3, ux-r0-2 |

Nothing under `src/uccc_genomics/`, `dashboard/` or `systemd/` changes. `web/src/styles.css` does
not change.

### 1. `web/src/Answer.tsx`

**Pivot legend (code-r0-1).** In `PivotTab`, the line

```tsx
<p className="legend">Blank combinations are 0 patients.</p>
```

becomes

```tsx
<p className="legend">0 means no patients have that combination; &lt;{minCell} means fewer than {minCell}.</p>
```

`minCell` is `PivotTab`'s existing prop (the result's `min_cell`), so the legend follows the
floor the server applied. `renderToStaticMarkup` renders it as `0 means no patients have that
combination; &lt;5 means fewer than 5.` for `min_cell: 5`.

**Dimming (ux-r0-2).** In `Answer`, the body wrapper

```tsx
<div className={busy || stale ? "answer-body dim" : "answer-body"}>
```

becomes

```tsx
<div className={busy ? "answer-body dim" : "answer-body"}>
```

`stale` stays: `Loosen` still gets it, so Drop buttons are still disabled while stale. A stale
answer that is not busy only happens after a failed `refresh` (App.tsx sets `busy` in the same
batch as every edit, and clears it in `finally`), and then the error alert with Retry is shown.
So the stale state is still flagged, and the body keeps full contrast.

### 2. `web/src/answer.test.tsx`

All synthetic, reusing the file's `kras`, `alk`, `def`, `result()` and `render()`.

- **"pivot: a null cell renders <5 in its td; an omitted cell is a known zero"**: add
  `expect(html).toContain("0 means no patients have that combination; &lt;5 means fewer than 5.");`
  and `expect(html).not.toContain("Blank combinations");`.
- **"labels come from the counted definition; Drop is disabled while stale, and the body is
  dimmed"** is renamed **"labels come from the counted definition; Drop is disabled while stale"**.
  Its `expect(html).toContain('class="answer-body dim"')` becomes
  `expect(html).not.toContain("dim")` (stale, not busy). The `expect(render(result())).not.toContain("dim")`
  line stays.
- New test in `describe("states")`, **"the body is dimmed only while busy"**:
  `expect(render(result(), "Accrual", {busy: true})).toContain('class="answer-body dim"')` and
  `expect(render(result(), "Accrual", {busy: false})).not.toContain("dim")`.
- New test in `describe("tabs")`, **"breakdown: a stale answer shows the counted breakdown"**:

  ```tsx
  const edited: Definition = {...def, breakdown: ["sex", "age_band"]};
  const counted: Counted = {d: def, r: result(), p: null};
  const html = renderToStaticMarkup(<Answer definition={edited} answer={counted} options={null} tab="Breakdown"
    onTab={() => {}} onOp={() => {}} />);
  expect(html).toContain('role="region" aria-label="Sex"');
  expect(html).not.toContain('aria-label="Age band"');
  ```

  Reverting `BreakdownTab` to map over `chosen` (`d.breakdown`) renders an "Age band" region and
  fails it.
- New test in `describe("tabs")`, **"pivot: a stale answer labels criterion axes from the counted
  definition"**:

  ```tsx
  const egfr = {...alk, gene: ["EGFR"], aa: [], class: ["mutation"]} as Criterion;   // same id c2
  const countedD: Definition = {...def, pivot: {rows: "c2.key", cols: "year"}};
  const edited: Definition = {...countedD, criteria: [kras, egfr]};
  const pivot: PivotResult = {
    cohort_id: "abc", rows: "c2.key", cols: "year", patients: 8, min_cell: 5, notes: [],
    cells: [{row: "ALK", col: "2023", patients: 6}],
    row_totals: [{value: "ALK", patients: 6}], col_totals: [{value: "2023", patients: 6}],
  };
  const html = renderToStaticMarkup(<Answer definition={edited} answer={{d: countedD, r: result(), p: pivot}}
    options={null} tab="Pivot" onTab={() => {}} onOp={() => {}} />);
  expect(html).toContain("<caption>c2 · ALK fusion · gene × Year of first qualifying report</caption>");
  expect(html).toContain('<th scope="col">c2 · ALK fusion · gene</th>');
  expect(html).not.toMatch(/<caption>[^<]*EGFR/);
  ```

  The row/column `<select>` options intentionally come from `definition` (they edit it), so the
  test does not assert that "EGFR" is absent from the whole page. Reverting `label` in `PivotTab`
  to `pivotAxes(d)` makes the caption read "c2 · EGFR mutation · gene" and fails it.

### 3. `mcp/src/uccc_genomics_mcp/app.py`

**`INSTRUCTIONS` (ux-r0-3 and code-r0-2 / ux-r1-1).** The sentence `reports counts reports.`
becomes `reports counts the cohort patients' in-population reports (Caris and FMI) that match at
least one criterion, or every population report when there are no criteria; it is not a patient
count.` This is what `compile.py` computes: `reports` is `count(*) FROM hit`, where `hit` is the
population reports of cohort patients matching at least one criterion's `m{i}`, or all of `pop`
when there are no criteria. The rest of the text does not change. The whole constant becomes
exactly:

```python
INSTRUCTIONS = (
    "Build a cohort definition (its JSON Schema comes from describe_definition), edit it with apply_op, map "
    "the user's words to vocabulary values with search_vocabulary, then count it, or pivot it once its pivot "
    "is set. patients, denominator, the funnel and years count distinct patients across Caris and FMI (a "
    "patient with reports from both vendors counts once). A breakdown or pivot cell counts the patients with "
    "a report having that value, so one patient can be in several cells and cells need not add up to "
    "patients. reports counts the cohort patients' in-population reports (Caris and FMI) that match at least "
    "one criterion, or every population report when there are no criteria; it is not a patient count. null "
    "means suppressed (1-4, or recoverable by subtraction), never zero. Quote only numbers a tool returned. "
    "Never claim the data holds stage, treatment, outcomes, race or ethnicity. Saved cohorts belong to the "
    "logged-in user: save_cohort, then edit with apply_saved_op (each edit is a new revision; "
    "revert_saved_cohort undoes). Saved cohorts hold no counts; count the head definition. Snapshots store "
    "the suppressed count with its data date for grant text.")
```

Every line is at most 110 characters. Apart from the `reports` sentence, the concatenated string
equals today's.

**`count` tool docstring (ux-r0-3).** It becomes:

```python
    """Count distinct patients matching a cohort definition: the funnel, breakdowns, years and, for
    a cohort too small to show, which criterion to loosen. null means suppressed, never zero.
    `denominator` is the patients in the population (in a breakdown cell: the population's patients
    with that value), the base for a percentage. `reports` counts the cohort patients' in-population
    reports (Caris and FMI) that match at least one criterion, or every population report when there
    are no criteria; it is not a patient count."""
```

Nothing else in `app.py` changes.

### 4. `tests/test_app.py`

- `test_tools_list`: add
  `assert all(f in tools["search_vocabulary"]["description"] for f in FIELDS)` (`FIELDS` is already
  imported). It pins the #66 docstring fix.
- `test_instructions_say_how_cells_overlap`: replace `assert "reports counts reports" in text` with
  `assert "reports counts the cohort patients' in-population reports" in text` and
  `assert "it is not a patient count" in text`. The other three assertions stay.

### 5. `README.md`, "Cohort app (genomics-app)" ((#60) code-r0-1, ux-r0-2)

The paragraph from `` `mcp/src/uccc_genomics_mcp/app.py`: the campus cohort site's backend `` through
"there is no SQL tool." becomes exactly:

```markdown
`mcp/src/uccc_genomics_mcp/app.py`: the campus cohort site's backend (docs/ARCHITECTURE.md). One
process serves REST at `/api/*` (OpenAPI schema at `/api/openapi.json`; no Swagger UI) and MCP
(Streamable HTTP, stateless) at `/mcp` (POST only; `GET /mcp` is 405, no SSE stream), both thin
layers over `cohort/`. Every request but `/api/health` needs a login through `authen`
(`--auth access|password|none`; `none`: no login, local dev only). `count` and `pivot` are limited
to 60 a minute per user across both surfaces (a count or pivot the cohort module rejects, such as
an unknown vocabulary value or a pivot of a definition that has no pivot, still uses the limit; a
body that fails schema validation does not) and logged to stdout as one JSON line each (user,
cohort_id, definition, suppressed patients). The MCP tools are `search_vocabulary`, `apply_op`,
`count`, `pivot` and `describe_definition`, plus the saved-cohort tools below; there is no SQL
tool.
```

Only the example changes ("an unknown value or a pivot with no rows/cols" → "an unknown vocabulary
value or a pivot of a definition that has no pivot"). The example is accurate: a pivot of a
definition without a pivot raises `DefinitionError("pivot: the definition has no pivot")` inside
`run_pivot`, after the limit is charged. A `Pivot` without `rows`/`cols` fails schema validation
(422) first. Every line is at most 100 characters.

### 6. `docs/ARCHITECTURE.md`, decision 7 (security-r0-1)

"so the lookup shows whether anyone has saved a given definition (an existence oracle)" becomes
"so the lookup shows whether anyone has ever saved a given definition (an existence oracle)".
Re-wrap the paragraph's lines if one goes past about 100 columns, keeping the 3-space hanging
indent. Nothing else changes.

### 7. `docs/specs/36-saved-cohorts-in-postgres-versions.md`, Risks (security-r0-1)

In the "`cohort_id` is a cross-user existence oracle" bullet, the sentence "A 200 means some user
has saved or snapshotted that definition; a 404 means nobody has." becomes "A 200 means some user
has ever saved, edited to or snapshotted that definition (version rows outlive deletion); a 404
means nobody has." Re-wrap the bullet at about 100 columns with its 2-space indent. The rest of the
bullet is unchanged.

The wording is accurate: `cohort_version` rows are "immutable, never deleted" (`saved.py`), and
`_upsert_version` runs on create, on every `_append` (apply and revert) and on `add_snapshot`.

### 8. `docs/specs/56-follow-ups-from-the-36-review.md` (security-r0-1)

Same two edits in the copies it carries: the Risks-bullet block under "**Risks section**" gets the
sentence from §7, and the ARCHITECTURE block under "### 4." gets "anyone has ever saved". Re-wrap
each block at about 100 columns.

### 9. `docs/specs/37-discover-react-app-for-building-cohorts.md` (code-r0-3, code-r0-5)

- **§3.3 doc-update item (code-r0-5).** In the `dashboard/COHORT_DISCOVERY.md` §3.3 bullet of the
  doc-update list, the parenthesis becomes the COHORT_DISCOVERY.md wording:
  "(saved cohorts (#36) store only the cohorts a user saves; Discover does not call `/api/saved*`
  yet, so a link carries the definition, and `/c/<cohort_id>` comes when Discover uses saved
  cohorts); the include/exclude toggle, ...". Re-wrap the bullet at about 100 columns.
- **"`localStorage` versions" Risks bullet (code-r0-3).** It becomes:

  ```markdown
  - **`localStorage` versions** are per browser and per origin, and vanish with site data. Saved
    cohorts (#36) persist what a user saves; Discover does not call `/api/saved*` yet, so unsaved
    versions stay in the browser.
  ```

- The "Share links hold the definition" bullet keeps its text; re-wrap its overlong last line at
  about 100 columns. The "Deviation from the issue" paragraph is not edited.

### 10. `docs/specs/54-follow-ups-from-the-35-review.md` ((#60) ux-r0-2)

In the `README.md` ("Cohort app (genomics-app)") bullet list, "such as an unknown value or a pivot
with no rows/cols" becomes "such as an unknown vocabulary value or a pivot of a definition that has
no pivot". Re-wrap the bullet at about 100 columns.

### 11. `docs/specs/58-follow-ups-from-the-37-review.md` (code-r0-1, code-r0-3, ux-r0-2)

- "Known zeros", the `PivotTab` bullet: the legend sentence becomes
  `` `<p className="legend">0 means no patients have that combination; &lt;{minCell} means fewer than {minCell}.</p>` `` (#65).
- Goal 5: "a result that is in flight or stale is dimmed" → "a result that is in flight is dimmed
  (#65: not while stale; the error alert flags that)".
- "Dimming" bullet: the wrapper becomes `<div className={busy ? "answer-body dim" : "answer-body"}>`
  (#65).
- Acceptance criteria: "the body carries `dim` while stale or busy" → "the body carries `dim` while
  busy (#65)".
- Test plan item 5, "stale labels": "and the body has `dim`" → "and the body has no `dim` (not
  busy; #65)".
- §Docs, the spec #37 bullet: the sub-item that lists "the two Risks bullets ("Share links hold the
  definition", "`localStorage` versions")" names only the "Share links hold the definition" bullet,
  and a new sub-item says: the "`localStorage` versions" bullet ends with "Saved cohorts (#36)
  persist what a user saves; Discover does not call `/api/saved*` yet, so unsaved versions stay in
  the browser." (#65).

### Docs and the design record

The ARCHITECTURE decision 7 edit is part of this change (§6). No design doc contradicts it:
COHORT_DISCOVERY.md, COHORT_TOOL.md, PLAN.md and AGENTS.md need no edit.

### What leaves the host

Nothing new. No endpoint, tool, page or loader changes what it returns; the pivot legend is static
text around counts that were already suppressed (`<{minCell}` for null cells). The small-cell rule
(floor 5, secondary suppression, the whole-cohort rule) is unchanged everywhere. `research_id` and
`report_id` are not touched.

## Acceptance criteria

- [ ] `grep -rn "Blank combinations" web/src docs/specs/58-follow-ups-from-the-37-review.md` finds
      nothing. The pivot tab renders "0 means no patients have that combination; &lt;5 means fewer
      than 5." for `min_cell: 5`.
- [ ] `Answer.tsx` dims the body with `busy` only: a stale, not-busy render has no `dim`; a busy
      render has `class="answer-body dim"`. Drop buttons are still disabled while stale.
- [ ] `web/src/answer.test.tsx` has the two new stale tests (Breakdown, Pivot) and the busy-dim
      test. Each fails if, respectively, `BreakdownTab` maps over `d.breakdown`, `PivotTab`'s
      `label` uses `pivotAxes(d)`, or the wrapper uses `busy || stale` (checked by making each
      change locally and running `bun test`, then reverting).
- [ ] `test_tools_list` asserts every name in `FIELDS` appears in the `search_vocabulary`
      description.
- [ ] `app.INSTRUCTIONS` contains "reports counts the cohort patients' in-population reports" and
      "it is not a patient count", not "reports counts reports". Every line of the `INSTRUCTIONS`
      block is at most 110 characters. The MCP `count` docstring contains "it is not a patient
      count" and no longer contains "`reports` counts reports, not patients".
- [ ] README "Cohort app (genomics-app)" paragraph matches §5; no line in it exceeds 100
      characters; `grep -rn "rows/cols" README.md docs/specs/54-follow-ups-from-the-35-review.md`
      finds nothing.
- [ ] `grep -rn "anyone has saved\|has saved or" docs/ARCHITECTURE.md docs/specs/36-*.md docs/specs/56-*.md`
      finds nothing; each of the three files says "ever saved" and the two spec Risks bullets say
      "version rows outlive deletion".
- [ ] `grep -n "cohorts\.)" docs/specs/37-discover-react-app-for-building-cohorts.md` finds
      nothing. The "`localStorage` versions" bullet ends "so unsaved versions stay in the browser."
- [ ] Spec #58's Goal 5, Dimming bullet, acceptance list, test plan item 5 and §Docs read as §11.
- [ ] `web/openapi.json`, `web/src/api.gen.ts`, `web/src/styles.css` and nothing under
      `src/uccc_genomics/`, `dashboard/` or `systemd/` change.
- [ ] `uv run pytest -q`, and `cd web && bun install --frozen-lockfile && bun run typecheck && bun
      test` pass.

## Test plan

- `web/src/answer.test.tsx` (§2): the legend assertion in the pivot test; the renamed stale-labels
  test (no `dim` while stale and not busy); "the body is dimmed only while busy"; "breakdown: a
  stale answer shows the counted breakdown"; "pivot: a stale answer labels criterion axes from the
  counted definition". All render synthetic definitions (KRAS G12C, ALK fusion, EGFR mutation) and
  synthetic counts with `renderToStaticMarkup`.
- `tests/test_app.py` (§4): `test_tools_list` (FIELDS in the description) and
  `test_instructions_say_how_cells_overlap` (new `reports` wording). Both use the existing
  synthetic mart fixture or no data at all.
- Run: `uv run pytest -q` (Postgres tests skip without `TEST_DATABASE_URL`; the changed tests do
  not need it) and `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`.
- Dashboard check: n/a (nothing under `dashboard/` changes).
- No `$DATA`, raw vendor file or PHI file is read. The doc edits use column names and synthetic
  examples only, no real counts, values or identifiers.

## Risks

- **A stale answer after a failure is no longer dimmed.** Someone could read the old numbers as
  current if they miss the error alert. The alert sits at the top of the answer column with a
  Retry button, and Drop buttons stay disabled, which the issue judged enough. Dimming at `.55`
  still applies while busy, where muted text is below 4.5:1 contrast for the length of a request;
  that is a loading state, not something users read.
- **Re-wrapping changes many lines for no text change.** `git diff --word-diff` on README.md and the
  specs shows only the intended wording edits; a reviewer should use it.
- **Hand-wrapped strings can drift.** The `INSTRUCTIONS` assertion uses
  `" ".join(app.INSTRUCTIONS.split())`, so the wrap points do not matter to the test; a missing
  trailing space between fragments would, and the exact block in §3 has them.
