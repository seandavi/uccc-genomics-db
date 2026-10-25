# Spec #58: follow-ups from the #37 review

Issue #58 lists thirteen minor and nit findings from the #37 review (the Discover app in `web/`)
that were not fixed before the merge. Ten are in `web/`, one is in `app.py` and the vocabulary,
and two are doc fixes. This spec fixes all thirteen in one PR. Each section below names the
finding id from the issue.

## Goal

1. The answer column labels a result with the definition it was counted for, not the one being
   edited (code-r0-1).
2. A known zero is drawn as zero: no hatching, and no "–" for a pivot cell that is an exact
   zero (code-r0-2, ux-r0-6).
3. Opening the Pivot tab on an unchanged definition does not re-run `count` (code-r0-3).
4. Search and value-list failures say they failed instead of looking like "no values"
   (ux-r0-2).
5. An edit error shows next to the column whose control caused it (ux-r0-4). An answer error
   has a Retry button, and a result that is in flight is dimmed (#65: not while stale; the error
   alert flags that) (ux-r0-8).
6. Pivot captions, breakdown headers, the Share card and the scroll regions read correctly
   (ux-r0-5, ux-r0-9, ux-r1-2, ux-r2-1).
7. `GET /api/options` and `search_vocabulary` reject a `field` outside the vocabulary's field set
   with a 400 / tool error that names `field`, and document the valid fields (ux-r0-7).
8. README run snippets work when pasted (ux-r0-3). Spec #37 and COHORT_DISCOVERY.md match the
   code (code-r0-4, code-r3-1).

## Non-goals

- No change to suppression (`cohort/suppress.py`), the compiler, the mart, `deid.py`, the
  loaders, `dashboard/` or `systemd/`. **`research_id` and `report_id` are not touched.**
- No new output path and no new number in any response. The web changes only re-render what
  the API already returns. The `app.py` change adds one error case to an existing endpoint.
- No change to the 60-a-minute rate limit or the `Transport` interface.
- Discover still doesn't call `/api/saved*`. Short links by `cohort_id` stay out of scope; only
  the documented reason changes (code-r3-1).
- No DOM test runner (no happy-dom or testing-library). The web tests stay
  `renderToStaticMarkup` + `bun:test`. Behaviour that needs effects or clicks (the refresh
  cache, the Typeahead error, Retry) is a manual acceptance check.

## Design

### Privacy and stability

- **Small cells.** Nothing new leaves the de-id file. Rendering an omitted pivot cell as `0`
  shows nothing new: `suppress_pivot` builds `cells` from `raw.cells` (the non-empty pairs
  only), so a pair missing from `cells` while its row and column are both listed is an exact
  zero. The zero is already known to anyone who reads the response, and `floor(0) == 0` is
  never suppressed (zeros are "known and never chosen" by `_line`). Every `null` still renders
  `<5` with the `suppressed` style. The Share card denominator now goes through `Count` too, so
  a suppressed denominator gets the same style and title it gets everywhere else.
- **Vocabulary.** The new field check runs before any lookup and its message names only the
  static field names, never a value or a count.
- `research_id` / `report_id`: unaffected (no pipeline change).

### Vocabulary field set (ux-r0-7)

`mcp/src/uccc_genomics_mcp/cohort/vocabulary.py`:

- Add a module constant, defined just above `VOCAB_SQL`. The SQL keeps writing its literals, and
  a test pins that the two agree:

  ```python
  # Every VocabEntry.field VOCAB_SQL can produce; `search(field=...)` accepts only these.
  FIELDS = tuple(f"population.{d}" for d in POP_DIMS) + (
      "alteration.gene", "alteration.aa", "biomarker.call", "ihc.marker", "ihc.clone", "ihc.call",
      "expression.gene", "specimen.site_type", "specimen.site", "actionability.evidence")
  ```

- `Vocabulary.search(self, q, limit=20, field=None, parent=None)`: the first statement becomes

  ```python
  if field is not None and field not in FIELDS:
      raise DefinitionError(f"field: {field!r} is not a vocabulary field; use one of {', '.join(FIELDS)}")
  ```

  Then the existing body runs unchanged. The check doesn't depend on `entries`, so a valid field
  on an empty mart still returns `[]`, not an error. Extend the docstring with "Raises
  DefinitionError for a field outside FIELDS."

`mcp/src/uccc_genomics_mcp/app.py`:

- `from fastapi import Depends, FastAPI, HTTPException, Query, Request` (FastAPI 0.162 is
  locked. `Query(description=...)` inside `Annotated` is the documented form).
- Write the field list once, near `Option`, built from `cohort.vocabulary.FIELDS` (import it as
  `from uccc_genomics_mcp.cohort.vocabulary import FIELDS`):

  ```python
  FIELD_HELP = ("Only this vocabulary field's values (q may then be empty); one of "
                + ", ".join(FIELDS) + ". Any other value is a 400.")
  ```

- `GET /api/options`: `field: Annotated[str | None, Query(description=FIELD_HELP)] = None` and
  `parent: Annotated[str | None, Query(description="With field: only values under this parent "
  "(alteration.aa: gene; biomarker.call: TMB/MSI/LOH; ihc.clone, ihc.call: marker)")] = None`.
  The existing `DefinitionError` handler already turns the raise into a 400 with `detail`.
- `search_vocabulary`: the docstring lists the valid fields by name (written out in the
  docstring, since a docstring can't be built at runtime) and says an unknown field is an
  error. The body becomes `try: return run_options(...) except DefinitionError as e: raise
  ToolError(str(e)) from None`, which matches `apply_op`.
- Run `cd web && bun run gen`. It regenerates `web/openapi.json` (the new descriptions) and
  `web/src/api.gen.ts` (JSDoc only). `test_openapi_snapshot` and `bun run typecheck` fail
  until it has been run.

### Moving the error text into `transport.ts` (needed by ux-r0-2)

Move `describe(e: unknown): string` out of `web/src/App.tsx`, unchanged, into
`web/src/transport.ts` as `export function describeError(e: unknown): string`. That way
`Builder.tsx` can use it without importing from `App.tsx`, which would be a cycle. App uses
`describeError` at every place it used `describe`. The name `describe` would also shadow
`bun:test`'s `describe` in any test that imports it.

### Answer state (code-r0-1, code-r0-3, ux-r0-4, ux-r0-8)

`web/src/Answer.tsx` exports:

```ts
/** The last good answer and the definition it was counted for (it can trail the one being edited). */
export interface Counted { d: Definition; r: CountResult; p: PivotResult | null }

export interface AnswerProps {
  definition: Definition;           // current version: breakdown checkboxes and pivot selects edit it
  answer: Counted | null;
  options: Options | null;
  tab: Tab;
  onTab: (t: Tab) => void;
  onOp: (op: Operation) => void;
  onRetry?: () => void;
  busy?: boolean;
  error?: string | null;            // count/pivot failure: shown with a Retry button
  editError?: string | null;        // an edit made from this column failed
}
```

`result` and `pivot` props are removed. Inside `Answer`, `const {d: counted, r, p: pivot} =
answer` and `const stale = answer.d !== definition`.

- **Labels come from `counted`.** `Cards`, `Funnel`, `Loosen`, the breakdown tables, and the
  pivot caption and corner cell get `counted`. Only the breakdown checkboxes and the pivot
  selects get `definition`. `BreakdownTab({r, counted, d, onOp})` builds its tables from
  `counted.breakdown`, and its checkboxes from `d.breakdown`, as they are built today.
- **Drop ids.** `Loosen({r, d: counted, stale, onOp})` gives each Drop button
  `disabled={stale}`. `l.drop` is an id in `counted`, and `edit()` applies the op to the current
  version, where that id may now be a different criterion (`add_criterion` reuses max+1). A
  disabled Drop button comes back once the refresh lands.
- **Dimming.** Wrap everything after the error paragraphs (from the sr-only live region to the
  tabpanel) in `<div className={busy ? "answer-body dim" : "answer-body"}>` (#65).
  `styles.css`: `.dim { opacity: .55; transition: opacity .15s; }`.
- **Errors.** In this order at the top of `<main>`:
  `{editError && <p role="alert" className="error">{editError}</p>}`, then
  `{error && <p role="alert" className="error">{error}{onRetry && <> <button type="button"
  onClick={onRetry}>Retry</button></>}</p>}`.

`web/src/App.tsx`:

- Replace the `result` and `pivot` state with `const [answer, setAnswer] = useState<Counted |
  null>(null)` and `const answerRef = useRef(answer)`. Keep the ref in step with the state,
  the same way `histRef` follows `hist`: one `setAnswerBoth(a)` helper that writes both.
- `refresh` keeps its sequence guard and caches the last count, one entry deep:

  ```ts
  const last = answerRef.current;
  const same = last?.d === d;   // definitions are immutable objects: identity is "unchanged"
  const r = same ? last.r : await transport.count(d);
  if (mine !== seq.current) return;
  const p = tabRef.current === "Pivot" && d.pivot ? (same && last.p) || await transport.pivot(d) : null;
  if (mine !== seq.current) return;
  setAnswerBoth({d, r, p});
  setAnswerError(null);
  ```

  This is how code-r0-3 is fixed. The tab effect stays `if (tab === "Pivot") refresh()`, but
  for an unchanged definition the refresh now sends only `pivot`, or nothing at all if that
  pivot is already held. The fix keeps the one existing guard, so nothing can race a refresh
  that is in flight. Every edit, version switch and share-link load produces a different
  definition object, so each of them still counts. A Retry after a failed count counts again,
  because nothing was cached for that definition.
- `editError` becomes `{at: "builder" | "answer"; message: string} | null`.
  `edit(op: Operation, at: "builder" | "answer")` records `at`. Builder (and the rename, which
  is a builder-column control) passes `"builder"`. `<Answer onOp={(op) => edit(op, "answer")}>`
  passes `"answer"`. The share-link load error is `at: "builder"`. The builder column renders
  the message only when `at === "builder"`, and `Answer` gets `editError={editError?.at ===
  "answer" ? editError.message : null}`. Each error renders in one place, so screen readers hear
  one alert, not two.
- `<Answer definition={current} answer={answer} … onRetry={refresh} busy={busy}
  error={answerError} />`. The header `cohort_id` reads `answer.r.cohort_id`.

### Known zeros (code-r0-2, ux-r0-6)

- `Funnel`: the track is `s.patients == null` → `bar hatched` (8%); else `!top` → `<span
  className="bar" style={{width: "0%"}} />`; else the scaled bar as today. A step that is 0 when
  the top is greater than 0 keeps today's `Math.max(1, …)` sliver.
- `PivotTab`: a `(row, col)` pair missing from `pivot.cells` renders `<td>0</td>`. Add one
  sentence under the table: `<p className="legend">0 means no patients have that combination;
  &lt;{minCell} means fewer than {minCell}.</p>` (#65). The test changes from `<td>–</td>` to `<td>0</td>`.

### Search and value errors (ux-r0-2), `web/src/Builder.tsx`

- `Typeahead` gets `const [error, setError] = useState<string | null>(null)`. When the effect
  closes or goes under `minChars`, it sets `setItems(null); setError(null)`. On success it sets
  `setError(null)`. On failure, `if (!stale) { setItems(null); setError(describeError(e)); }`.
  It renders `{st.open && error && <p role="alert" className="error">Could not search:
  {" "}{error}</p>}`. The "No matching values" hint still needs `shown.length === 0`, which
  `items === null` can never meet.
- `useValues(transport, field, parent?)` returns `{values: string[]; error: string | null}`.
  The `.catch` sets `error` to `describeError(e)`, and a new load clears it. Each caller
  destructures it (`const aa = useValues(…)`, then `aa.values` / `aa.error`).
- `Checks` gains `error?: string | null` and, inside the fieldset after the legend, renders
  `{error && <p role="alert" className="error">Could not load values: {error}</p>}`. Every
  `Checks` fed by `useValues` passes its `error`: population checks, biomarker calls, IHC
  calls, specimen site type and site, actionability evidence, and alteration `aa`. The `aa`
  group's condition becomes `oneGene && mutationOnly && (aa.values.length > 0 || aa.error)`.
  The IHC clone `<select>` gets the same paragraph after it when `clones.error` is set.
- `export` the `Checks` function so that the test can render it.

### Labels and accessibility (ux-r0-5, ux-r0-9, ux-r1-2, ux-r2-1)

- `GridTable({label, children}: {label: string; children: ReactNode})` renders `<div
  className="table-scroll" tabIndex={0} role="region" aria-label={label}><table
  className="grid"><caption>{label}</caption>{children}</table></div>`. Callers stop writing
  their own `<caption>`. The breakdown label is the `BREAKDOWN_DIMS` label, and the pivot label
  is ``${label(pivot.rows)} × ${label(pivot.cols)}``.
- `PivotTab({d, counted, pivot, minCell, onOp})`: `const label = (v: string) =>
  pivotAxes(counted).find((a) => a.value === v)?.label ?? v;`. The caption and the corner `<th>`
  use `label(pivot.rows)` / `label(pivot.cols)`, which are the axes of the result shown, not
  the local select state. The selects keep `pivotAxes(d)`.
- Accrual `.bars`: add `role="group" aria-label="Patients by year of first qualifying report"`,
  and `aria-hidden="true"` on each `.barlabel`. The sr-only table already carries the numbers,
  so they are read once.
- `styles.css`: the sticky rule becomes `table.grid th[scope="row"], table.grid thead
  th:first-child { position: sticky; left: 0; background: var(--bg); }`.
- Breakdown header `Of` becomes `Of patients in population`.
- Share card sub-line: `const pop = populationLabel(counted.population);` then `of <Count
  n={r.denominator} minCell={r.min_cell} /> patients {pop === "All patients" ? "(all
  patients)" : `in ${pop}`}`.

### Docs

- `README.md`: the Discover snippet becomes `(cd web && bun install && bun run build)` (ux-r0-3).
  The two `cd dashboard && npm test` / `cd web && …` lines in the Commands block break the same
  way when pasted together (the second `cd` runs inside `dashboard/`), so they become subshells
  too, matching AGENTS.md.
- `docs/specs/37-discover-react-app-for-building-cohorts.md` (code-r0-4, code-r3-1, ux-r0-7):
  - The `fetchTransport` signature becomes `export type FetchLike = (input: string, init?:
    RequestInit) => Promise<Response>;` + `export function fetchTransport(fetchImpl: FetchLike
    = fetch): Transport`.
  - The files-table row and test plan item 1 say "add `test_search_field_and_parent`" in place
    of "extend `test_search`".
  - The openapi-typescript paragraph: fields with a non-null default are marked required.
    Fields whose default is `null` are optional (`id?`, `pivot?`, `at_least?`, `clone?`,
    `measure?`).
  - "An unknown field returns no entries (no error)" becomes "A field outside the vocabulary's
    field set is a 400 / tool error naming `field` (#58)".
  - The "Deviation from the issue" paragraph, the §3.3 doc-update item, and the Risks bullet
    "Share links hold the definition": replace the stale reason with "Saved cohorts (#36) store only the cohorts a user saves. Discover does not call
    `/api/saved*` yet, so a link carries the definition; `/c/<cohort_id>` comes when Discover
    uses saved cohorts."
  - The "`localStorage` versions" bullet ends with "Saved cohorts (#36) persist what a user
    saves; Discover does not call `/api/saved*` yet, so unsaved versions stay in the browser."
    (#65).
- `dashboard/COHORT_DISCOVERY.md`: the "Phase 1 (#37)" paragraph's parenthesis gets the same
  rewording (code-r3-1). The §3.5 sentence on `field` and `parent` adds "a field outside the
  vocabulary's field set is a 400 naming `field`".

No design doc contradicts this change. ARCHITECTURE.md and COHORT_TOOL.md need no edit.

## Acceptance criteria

- [ ] `Vocabulary.search("", field="no.such")` raises `DefinitionError` naming `field`.
      `search("", field="population.sex")` on an empty vocabulary returns `[]`. Every field in
      the synthetic mart's `entries` is in `FIELDS`, and every name in `FIELDS` appears in
      `VOCAB_SQL`.
- [ ] `GET /api/options?q=&field=alteration.genes` → 400 whose `detail` contains `field`;
      `search_vocabulary` with that field → `isError` and the text contains `field`.
- [ ] `/api/openapi.json` gives the `field` query parameter a description listing every name in
      `FIELDS`. `web/openapi.json` and `web/src/api.gen.ts` are regenerated
      (`test_openapi_snapshot` and `bun run typecheck` pass).
- [ ] Answer labels (funnel step, Loosen, Share card population, breakdown tables, pivot
      caption) come from `answer.d` when it differs from `definition`. Loosen's Drop buttons are
      disabled and the body carries `dim` while busy (#65).
- [ ] A funnel with `funnel[0].patients === 0` has no `bar hatched`. A null step is still
      hatched. An omitted pivot cell renders `<td>0</td>`. Every null still renders `<5` with
      `class="suppressed"`.
- [ ] The Share card denominator renders through `Count` (a null denominator is a `suppressed`
      span). An empty population reads "(all patients)". The breakdown header reads "Of
      patients in population".
- [ ] The pivot caption and corner cell show `pivotAxes` labels, not raw axis ids.
- [ ] `.table-scroll` has `role="region"` and an `aria-label` equal to its caption, `.bars` has
      `role="group"` and an `aria-label`, and `.barlabel` is `aria-hidden`.
- [ ] Answer renders `editError` in its own alert, and `error` with a Retry button when
      `onRetry` is given.
- [ ] `Checks` with `error` renders "Could not load values: …" in an alert.
- [ ] Manual (tailnet `genomics-app --auth password --static web/dist`): opening the Pivot tab
      on an unchanged definition sends one `POST /api/pivot` and no `POST /api/cohort` (Network
      panel). Switching tabs back and forth sends nothing. With the server stopped, typing in
      "Add criterion" shows "Could not search: …" and opening an editor shows "Could not load
      values: …". A loosen Drop that fails shows its error above the answer. Retry after a
      429 re-counts.
- [ ] README snippets use subshells. Spec #37 and COHORT_DISCOVERY.md carry the rewordings above.
- [ ] `uv run pytest -q`, `cd web && bun install --frozen-lockfile && bun run typecheck && bun
      test` pass. Dashboard check: n/a (nothing under `dashboard/` except the .md changes).

## Test plan

Python (`uv run pytest -q`). Synthetic data only: the existing `cohort_db` fixture builds the
#34 mart in a temp `DATA`, and nothing reads `$DATA/raw`, the PHI file or the real de-id file.

1. `tests/test_cohort.py::test_search_field_and_parent`: replace `v.search("", field="no.such")
   == []` with `pytest.raises(DefinitionError, match="field")`. Add `assert {e.field for e in
   v.entries} <= set(FIELDS)`, `assert all(f"'{f}'" in VOCAB_SQL for f in FIELDS if not
   f.startswith("population."))`, and `assert Vocabulary(entries=[], years=None).search("",
   field="population.sex") == []`.
2. `tests/test_app.py::ERRORS`: add `("GET", "/api/options?" + urlencode({"q": "", "field":
   "alteration.genes"}), None, "search_vocabulary", {"q": "", "field": "alteration.genes"},
   "field")`. It runs through `test_errors_agree` (REST 400 and MCP `isError`, both naming
   `field`). Its id (`e[5]`) is `"field"`, which no other entry uses.
3. `tests/test_app.py`: add `test_options_field_described`. In `client.get("/api/openapi.json",
   auth=AUTH)`, the `/api/options` `get` parameter named `field` has a `description` that
   contains every name in `FIELDS`.
4. `test_openapi_snapshot` passes after `bun run gen`.

Web (`bun test`, `renderToStaticMarkup`):

5. `web/src/answer.test.tsx`: the `render` helper takes `answer = {d, r, p: null}` with `d`
   defaulting to `def`, and the pivot test passes `p`. Update the pivot test to expect
   `<td>0</td>` for the omitted `LUAD × 2023` pair. New tests:
   - stale labels: `answer.d = def` (c2 = ALK fusion) and `definition = {...def, criteria:
     [kras, egfr]}`, where `egfr` is a new alteration criterion (`gene: ["EGFR"]`) with
     `id: "c2"`. The HTML contains "∧ ALK fusion", not EGFR, the Drop
     button has `disabled`, and the body has no `dim` (not busy; #65).
   - zero funnel: funnel all `0` → no `bar hatched`, and `width:0%` present.
   - Share card: `denominator: null` → `<span class="suppressed"` after "of ". An `EMPTY`
     population → "(all patients)".
   - breakdown header text "Of patients in population". The table wrapper has
     `role="region"` and `aria-label="Sex"`.
   - pivot caption uses the `pivotAxes` label for `oncotree` and `year` ("Year of first
     qualifying report"). The corner `<th>` uses it as well.
   - accrual: `role="group"` and `aria-hidden="true"` on `barlabel`.
   - errors: `editError` renders an alert. `error` with `onRetry` renders `>Retry</button>`.
6. New `web/src/builder.test.tsx`: `renderToStaticMarkup(<Checks legend="Site" values={[]}
   selected={[]} onChange={() => {}} error="request failed (500)" />)` contains `role="alert"`
   and "Could not load values: request failed (500)".
7. `web/src/transport.test.ts`: `describeError` maps a 401 and a 429 (with and without
   `retryAfter`) to today's text, so the move changes no message.

## Risks

- **The cache trusts object identity.** If a future code path rebuilt an equal definition as a
  new object, the only cost is one extra count. If one mutated a definition in place (none
  does; every edit goes through `apply`), the cache would serve the old count. The comment on
  `same` says this.
- **The field check breaks callers that relied on `[]`.** None in this repo: Discover only
  sends fields from `cohort.ts`, and the MCP instructions say to use `describe_definition`. An
  external MCP client that sent a misspelled field now gets an error instead of silence, which
  is the point.
- **`FIELDS` can drift from `VOCAB_SQL`.** Test 1 pins both directions.
- **Generated files.** The new `Query` descriptions change `openapi.json`, so the PR must run
  `bun run gen`. CI fails loudly if it doesn't.
