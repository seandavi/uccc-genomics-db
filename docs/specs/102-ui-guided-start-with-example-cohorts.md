# Spec #102: UI guided start with example cohorts (landing state)

Issue #102 is item 6 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, §1.3,
§2 "Desktop wireframe: landing", §3 item 6). It changes `web/` only, plus one paragraph of
`dashboard/COHORT_DISCOVERY.md` §3.3. It depends on #99 (answer hierarchy, merged) and #101 (builder
controls, merged).

## Problem

With an empty definition (no population values, no year window, no criteria) the answer column
draws a full answer for "all patients": the hero Patients card, an Accrual card with a tier, the
data footnote, the tab strip and the Accrual chart. Nothing on the page suggests a first step. #98
already removed the Assistant column and #99 already hides the Share card and the funnel for an
empty definition, so "100% of all patients" no longer renders. That leaves a page with an answer and
no question.

## Goal

When the **current** definition is empty (`isEmptyDefinition(definition)` in `cohort.ts`), the
answer column replaces the answer body with a guided start:

1. an intro line;
2. **"Start from an example"**: four example cohort cards from a synthetic `EXAMPLES: Definition[]`
   in `cohort.ts`. Each card shows the example's name and a label made from its definition, and a
   "Use →" button. Cards show **no counts**;
3. the whole-population total line, "Discover covers {count} patients sequenced by Caris and FMI.";
4. a small, muted accrual sparkline for all patients.

"Use →" applies the example through the same path a share link takes: `transport.apply(example,
{op: "rename", name})`, then `pushVersion`, then `setHist` (which writes the share hash), then
`refresh()`, then moves focus to the answer heading (`#answer-h`, always mounted) because the
landing that held the focused button unmounts. If the server rejects the example (a term not in the vocabulary), the answer column
shows "This example could not be used: {server message}" and no version is added.

## Non-goals

- **No new output path and no data change.** Nothing under `src/uccc_genomics/`, `mcp/`,
  `dashboard/src/` or `systemd/` changes. There is no schema, table, column, endpoint or MCP tool
  change, and `api.gen.ts` / `openapi.json` are unchanged. The example cards render only constant
  strings from `web/src/cohort.ts`. An applied example's counts come from the existing `POST
  /api/cohort` call, with the server's floor, neighbour checks and secondary suppression, and render
  through the existing `Count` component. The total line and the sparkline read the `CountResult`
  of the empty definition, which the page already fetches and shows today (hero card and Accrual
  tab). **`research_id` and `report_id` are not touched.**
- No pre-filtering of examples against the vocabulary (no `/api/options` call per example). The
  server's `vocab.check` in `cohort.apply` is the single check, and the error path covers a term
  that is missing.
- No change to the definition and operations model, the share-hash format (`shareHash` /
  `readShareHash`), `transport.ts`, the header, the builder, `SummaryBar`, Compare or the
  Feasibility panel.
- The tabs (Accrual, Breakdown, Pivot, Data notes), the data footnote and `Loosen` are not shown on
  the landing page. A `breakdown` or `pivot` stored on an empty definition stays in the definition
  and shows again once a population value or criterion is added.
- No new dependency and no DOM emulator. Tests use the existing `bun test` and
  `renderToStaticMarkup`, plus direct calls to exported functions, as #104 did.
- No CDN fonts or scripts, and no raw hex colours outside `:root` (`styles.test.ts` already enforces
  this).

## Design

Files: `web/src/cohort.ts`, `web/src/Start.tsx` (new), `web/src/Answer.tsx`, `web/src/App.tsx`,
`web/src/styles.css`, `web/src/cohort.test.ts`, `web/src/answer.test.tsx`, `web/src/app.test.tsx`
and `dashboard/COHORT_DISCOVERY.md`.

### `web/src/cohort.ts`: `EXAMPLES` and `exampleLabel`

Add these below `isEmptyDefinition`. The examples are synthetic definitions that use only generic,
public terms: OncoTree codes that appear in `src/uccc_genomics/data/disease_crosswalk.csv`, the HGNC
gene symbols EGFR, KRAS and BRAF, and the normalised MSI call `high` (`unified.biomarker.call_norm`,
`sql/unified.sql`). No name or label contains a digit. Acceptance (c) allows only years, and HER2,
ERBB2 and KRAS G12C carry digits, so those examples are out. Criterion ids are `c1`, which is
required by the server's `ID_RE` and never shown (#101 hides the `cid`). `tier: []` and
`vendor: null` follow `newCriterion`; the server normalises `tier` to its default.

```ts
/** Synthetic example cohorts for the guided start: generic public terms, shown by name and label only (no counts). */
export const EXAMPLES: Definition[] = [
  {...EMPTY, name: "EGFR-mutant lung cancer", population: {...EMPTY.population, oncotree: ["NSCLC"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["EGFR"], aa: [], class: ["mutation"], tier: []}]},
  {...EMPTY, name: "KRAS-mutant pancreatic cancer", population: {...EMPTY.population, oncotree: ["PAAD"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["KRAS"], aa: [], class: ["mutation"], tier: []}]},
  {...EMPTY, name: "MSI-high colorectal cancer", population: {...EMPTY.population, oncotree: ["COADREAD"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "biomarker", name: "MSI", call: ["high"], at_least: null}]},
  {...EMPTY, name: "BRAF-mutant melanoma", population: {...EMPTY.population, oncotree: ["MEL"]},
   criteria: [{id: "c1", mode: "include", vendor: null, kind: "alteration", gene: ["BRAF"], aa: [], class: ["mutation"], tier: []}]},
];

/** An example card's second line: its population, then each criterion, e.g. "NSCLC + EGFR mutation". */
export const exampleLabel = (d: Definition): string =>
  [populationLabel(d.population), ...d.criteria.map(criterionLabel)].join(" + ");
```

The labels this produces are "NSCLC + EGFR mutation", "PAAD + KRAS mutation", "COADREAD + MSI high"
and "MEL + BRAF mutation".

### `web/src/Start.tsx` (new): the landing view

The view lives in its own file so `Answer.tsx`, which #100 is also changing, gets only a
three-line hook.

```tsx
import { Count } from "./Answer.tsx";
import { EXAMPLES, exampleLabel } from "./cohort.ts";
import type { CountResult, Definition } from "./types.ts";

export interface StartProps {
  total: CountResult | null;   // the count of the current (empty) definition; null while it is counted
  busy: boolean;
  minCell: number;
  onExample: (d: Definition) => void;
}

/** The answer column for an empty definition: how it works, example cohorts (no counts), the total, a sparkline. */
export function Start({total, busy, minCell, onExample}: StartProps) { ... }
```

`Start.tsx` imports `Count` from `Answer.tsx`, and `Answer.tsx` imports `Start` from
`Start.tsx`. This cycle is safe because both are used only inside function bodies at render time.
Markup, in this order:

```tsx
<section className="start" aria-labelledby="start-h">
  <p className="intro">How many of our sequenced patients fit your study? Pick who in the builder, add criteria,
    then copy a feasibility statement. Counts under {minCell} show as {`<${minCell}`}.</p>
  <h3 id="start-h">Start from an example</h3>
  <ul className="examples">
    {EXAMPLES.map((d) => (
      <li key={d.name} className="card example">
        <h4>{d.name}</h4>
        <p className="sub">{exampleLabel(d)}</p>
        <button type="button" className="btn-secondary" aria-label={`Use example: ${d.name}`}
          onClick={() => onExample(d)}>Use →</button>
      </li>
    ))}
  </ul>
  {total
    ? <p className="total">Discover covers <Count n={total.patients} minCell={total.min_cell} /> patients sequenced by Caris and FMI.</p>
    : busy && <p className="total">Counting…</p>}
  {total && <Sparkline r={total} />}
</section>
```

- The "Use →" buttons are `btn-secondary`. The review's control table (§2) allows one primary per
  view, and the header's Feasibility statement already holds it. `app.test.tsx` pins one
  `btn-primary` in the header.
- The `aria-label` starts with the visible word "Use", which satisfies label-in-name. It tells the
  four buttons apart for screen readers.
- `Sparkline` is a non-exported function in `Start.tsx`. It renders nothing when `r.by_year` is
  empty. Otherwise:

```tsx
<figure className="spark">
  <div className="spark-bars" aria-hidden="true">
    {r.by_year.map((y) => (
      <span key={y.year} className={["vbar", y.patients == null && "hatched", !y.complete && "partial"].filter(Boolean).join(" ")}
        style={{height: `${height(y.patients)}%`}} />
    ))}
  </div>
  <figcaption>Patients by year of first qualifying report, {first}–{last}</figcaption>
</figure>
```

  - `first` and `last` are the min and max `year` in `r.by_year`, and `max` is
    `Math.max(1, ...r.by_year.map((y) => y.patients ?? 0))`.
  - The bars show no numbers. They are context only; the per-year counts, with "<5" labels, are in
    the Accrual tab of any non-empty cohort.
  - Heights follow #100's rule: a suppressed year is drawn as if it were `min_cell`, so it is never
    taller than a shown bar of `min_cell` or more, with a 2% floor and a 100% cap. If `barPct` from
    #100 is on `origin/main` when this is implemented, use
    `height = (n: number | null) => barPct(n, max, r.min_cell)`. Otherwise use the identical inline
    `const height = (n: number | null) => Math.min(100, Math.max(2, ((n ?? r.min_cell) / max) * 100));`
    with the comment `// same rule as barPct (#100)`. The integrate stage swaps in `barPct` if #100
    lands first. `by_year` never lists a year with 0 patients (`suppress.py` emits only years with
    patients), so the two forms agree.
  - Gap years are not filled in. The sparkline is a muted context strip with no axis labels, and
    `yearSlots` (#100) is not needed for it.

### `web/src/Answer.tsx`: show `Start` for an empty definition

- Add one optional prop to `AnswerProps`:
  `onExample?: (d: Definition) => void;   // the guided start's "Use →"`.
- In `Answer`, after the two error paragraphs, replace the `{!answer ? … : (() => {…})()}`
  expression with:

```tsx
{isEmptyDefinition(definition)
  ? <Start total={answer && answer.d === definition ? answer.r : null} busy={busy}
      minCell={options?.min_cell ?? 5} onExample={onExample ?? (() => {})} />
  : !answer ? … : (() => {…})()}
```

  The existing branches stay byte-for-byte the same. The `<h2 id="answer-h">` heading ("Your
  cohort" for an unnamed definition) still renders above `Start`, so the `SummaryBar` "View" link
  and its focus still work.
- `answer.d === definition` (identity, as `stale` already uses) keeps the landing from showing a
  total that was counted for a different definition. For example, right after the last criterion
  is removed, the landing shows "Counting…" until the recount arrives.
- The existing `!isEmptyDefinition(counted)` checks in `Cards` and before `Funnel` stay. They still
  apply while a just-applied example is being counted, when the current definition is non-empty but
  the last answer is for the empty one.

### `web/src/App.tsx`: one apply path for share links and examples

Extract the request-and-push part of `applyShareHash` into an exported function that both callers
use:

```ts
/** d as a new version, through the server: apply(d, rename to its own name) validates it, against the vocabulary
 *  too, and returns its normal form. history() is read after the request, so an edit made meanwhile is kept;
 *  no version is added when the normal form equals the current version. Throws what transport.apply throws. */
export async function applyDefinition(d: Definition, history: () => History, transport: Pick<Transport, "apply">): Promise<History> {
  const n = (d as {name?: unknown}).name;   // a share link's JSON is unchecked until the server reads it
  const r = await transport.apply(d, {op: "rename", name: typeof n === "string" ? n : ""});
  const h = history();
  return JSON.stringify(r.definition) === JSON.stringify(h.versions[h.current].definition) ? h : pushVersion(h, r.definition);
}
```

`applyShareHash`'s `try` block becomes:

```ts
    const decoded = readShareHash(hash);
    if (decoded === null) throw new Error("it could not be read");
    return {history: await applyDefinition(decoded as Definition, history, transport)};
```

Its behaviour, doc comment, error text and tests stay as they are. In `App`, add the example
handler next to `edit`, and pass it to `Answer`:

```ts
  const applyExample = useCallback(async (d: Definition) => {
    try {
      setHist(await applyDefinition(d, () => histRef.current, transport));
      setEditError(null);
      refresh();
    } catch (e) {
      setEditError({at: "answer", message: `This example could not be used: ${describeError(e)}`});
    }
  }, [transport, setHist, refresh]);
```

```tsx
        <Answer … onExample={applyExample} … />
```

- The handler is named `applyExample`, not `useExample`: a `use` prefix reads as a React hook.
- `setHist` writes `localStorage` and the share hash (`replaceState(shareHash(d))`), and `refresh()`
  counts the new current version. That is acceptance (b): version n+1, a counted answer and an
  updated share hash.
- The error is set `at: "answer"`, so it shows at the top of the answer column, next to the button
  that was clicked. A server vocabulary rejection reads, for example, "This example could not be
  used: criteria.c1.gene: 'EGFR' is not in the vocabulary".

### `web/src/styles.css`

Add these under `/* answer */`. They use only existing tokens.

```css
.start .intro { margin: 0 0 var(--s5); max-width: 65ch; }
.examples { list-style: none; padding: 0; margin: var(--s2) 0 var(--s5); display: grid; grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr)); gap: var(--s3); }
.example { display: flex; flex-direction: column; gap: var(--s2); }
.example h4 { margin: 0; font-size: var(--fs-md); line-height: var(--lh-md); }
.example button { align-self: flex-end; margin-top: auto; }
.start .total { color: var(--muted); margin: 0 0 var(--s2); }
.spark { max-width: 16rem; }
.spark-bars { display: flex; align-items: flex-end; gap: 2px; height: 2rem; }
.spark .vbar { flex: 1; }
.spark .vbar.partial:not(.hatched) { background: var(--bar-partial); }
```

The existing `.vbar` and `.vbar.hatched` rules give the bar colour and the quiet hatch. The
existing `figcaption` rule makes the caption muted and small.

### `dashboard/COHORT_DISCOVERY.md` §3.3

In "Centre: answer", first bullet, replace the sentence "With an empty definition (no population
values and no criteria) the percentage card and the funnel are not shown." with:

> With an empty definition (no population values, no year window and no criteria) the answer
> column is a guided start instead (#102): an intro line, four example cohorts (synthetic
> definitions in `web/src/cohort.ts`, shown by name and label with no counts), the
> whole-population total and a small accrual sparkline. "Use →" applies an example through
> `/api/apply`, as a share link is applied, so its counts come from the ordinary `/api/cohort`
> call. While an example is being counted the cards show without the percentage card and the
> funnel.

The doc contradicts nothing else in this change. ARCHITECTURE.md, README.md, PLAN.md and
COHORT_TOOL.md are unchanged.

## Acceptance criteria

- [ ] (a) With an empty definition, the answer column shows the intro line, "Start from an
      example" with four cards (name, label, "Use →"), the total line and the sparkline. No card
      shows a number. The orchestrator verifies the screenshot on the dev server.
- [ ] (b) "Use →" on an example adds version n+1 holding the server's normal form of that
      definition, counts it, and writes its share hash. This is pinned by the `applyDefinition`
      unit tests and an `App.tsx` source check that `applyExample` goes through
      `applyDefinition`, `setHist`, `refresh` and the focus call (`jumpToAnswer`). The orchestrator verifies it end to end on the dev
      server.
- [ ] (c) A test renders `Start` and asserts that each example card's text, with 4-digit years
      removed, contains no digit. A `cohort.test.ts` test asserts the same for every `EXAMPLES` name
      and `exampleLabel`.
- [ ] (d) The landing page has no Assistant column, no "100%", no "Share of population", no
      funnel, no hero card and no tab strip.
- [ ] A rejected example shows "This example could not be used: …" in the answer column and adds
      no version: `applyDefinition` throws, and `applyExample` sets `editError` and never calls
      `setHist`.
- [ ] A suppressed total renders "<5" through `Count` (the `suppressed` span), never 0 or blank.
      A suppressed sparkline year is drawn hatched, at the `min_cell` height.
- [ ] A non-empty definition (a population value, a year window or a criterion) renders the
      existing answer, not `Start`.
- [ ] `applyShareHash` keeps all of its current tests passing unchanged.
- [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes.

## Test plan

These are all `web/` tests with synthetic `CountResult` fixtures. Nothing reads `$DATA`, the de-id
file or the PHI file. `uv run pytest -q` is n/a (no Python change); run it anyway if it is cheap.
The dashboard check is n/a.

**`web/src/cohort.test.ts`**, `describe("EXAMPLES")`:
- 3 ≤ `EXAMPLES.length` ≤ 5, and the names are unique and non-empty.
- Every example satisfies `!isEmptyDefinition(d)`, and every criterion id matches `/^c[1-9]\d{0,2}$/`.
- For each example, `d.name` and `exampleLabel(d)`, with `/\b(19|20)\d{2}\b/g` removed, do not
  match `/\d/`.
- `exampleLabel(EXAMPLES[0])` is `"NSCLC + EGFR mutation"`.

**`web/src/answer.test.tsx`**:
- Update "an empty definition shows no share card and no funnel" to cover the landing. For
  `render(result(), "Accrual", {}, EMPTY)`, the HTML:
  - contains "Start from an example", `class="examples"` and four `Use example:` labels;
  - contains "Discover covers" followed by the `8` total (the fixture's `patients`);
  - contains `class="spark"`;
  - does not contain "Share of population", `funnel-h`, `class="card hero"`, `role="tablist"`,
    `DATA_FOOTNOTE` or "100%".
- Keep the second half of that test as it is: with a year window, or with a criterion, it still
  shows "Share of population" and the funnel, and has no `class="examples"`.
- The landing with `result({patients: null})` renders `Discover covers <span class="suppressed"…>&lt;5</span>`
  and no `>0<`.
- The landing with an answer counted for a different definition
  (`<Answer definition={EMPTY} answer={{d: def, r: result(), p: null}} busy …/>`) shows
  "Counting…" and no "Discover covers".
- The sparkline for the fixture's `by_year` (2023: 6, 2024: null, 2025: 3 partial, `min_cell`
  5) renders three `vbar` spans:
  - the first is `height:100%`;
  - the null year has `hatched` and a height of `5 / 6 * 100` percent, which is the `min_cell`
    rule, not a fixed height;
  - the 2025 bar has `partial` and `height:50%`.

  The caption reads "…, 2023–2025", and no text node inside `class="spark-bars"` holds a digit.
- The example cards: slice each `<li class="card example">…</li>` from the HTML, strip the tags,
  remove `/\b(19|20)\d{2}\b/g`, and assert that no `/\d/` remains. This is acceptance (c).

**`web/src/app.test.tsx`**, `describe("applyDefinition")`, using the fake-`apply` helper style of
`describe("applyShareHash")`:
- For a history with one version and `EXAMPLES[0]`, the result has two versions, `current` is 1,
  `versions[1].n` is 2, and `versions[1].definition` is the definition the fake returned (pass a
  normalised copy, e.g. with `tier: ["likely_pathogenic", "pathogenic"]`, to show that the server's
  form is the one stored). The single call's op is `{op: "rename", name: EXAMPLES[0].name}`.
- A fake that throws `new TransportError("criteria.c1.gene: 'EGFR' is not in the vocabulary", 400)`
  makes `applyDefinition` reject with that error.
- A server form equal to the current definition returns the same history object (`toBe`).
- An edit made during the request is kept, as in the `applyShareHash` test of the same name.
- A source check on `App.tsx`:
  - `applyShareHash`'s body calls `applyDefinition(`;
  - the `applyExample` body contains `applyDefinition(`, `setHist(`, `refresh()` and
    "This example could not be used: ";
  - `onExample={applyExample}` is present.
- The existing header test (one `btn-primary` in the header, no Assistant) still passes. Its
  stalled transport means the landing shows "Counting…". Add `expect(html).toContain("Start from
  an example")` there.

## Risks

- **An example term leaves the vocabulary.** The vocabulary is floored daily, so a term can drop
  below 5 patients. "Use →" then shows the server's error and adds nothing. The landing still
  works, and the fix is to edit `EXAMPLES`. The orchestrator's dev-server check clicks every
  example.
- **Merge overlap with #100** (open, same files: `Answer.tsx`, `cohort.ts`, `styles.css`,
  `answer.test.tsx`). The landing view sits in a new `Start.tsx`, and `Answer.tsx` gets one
  conditional. The height rule is the one `barPct` encodes, and the spec says which form to use
  in either merge order.
- **Hidden tabs on the landing.** Someone who wants a breakdown of all patients has to add a
  population value first. The issue's landing scope lists only the four elements, and the review's
  wireframe has no tabs.
- **Example choice.** Acceptance (c) rules out digits, so the canonical KRAS G12C and HER2
  examples from the review's wireframe are out. The four chosen examples cover three alteration
  examples and one biomarker example across four tumor types.
- **Double click** on "Use →" sends two applies and can add two versions. Every other edit button
  behaves the same way today, and this spec does not change that.
