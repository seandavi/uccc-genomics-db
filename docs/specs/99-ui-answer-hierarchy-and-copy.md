# Spec #99: UI answer hierarchy and copy

Issue #99 is item 3 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, §1.1,
§2.3, §3.5-3.7, §2 type scale and wireframes, §3 item 3). It depends on #97 (design tokens,
merged). It changes the answer column of Discover in `web/` only. Owner decisions that bear on it
(2026-10-30): future years from date-shifting are handled in copy ("dates are shifted for
de-identification; the last years are partial"), not by clamping.

## Goal

1. The patient count is the hero: the Patients card spans about half the card row and its number
   is set at `--fs-hero` (44px), the largest type on the page. Accrual and Share are secondary
   cards with numbers at `--fs-2xl` (28px).
2. The Accrual card names its year window ("per year, 2023–2026") and shows one decimal below 10
   and whole numbers at 10 and above.
3. When the counted definition is empty (no population values, no year window, no criteria), the
   Share card and the funnel are not rendered.
4. The funnel heading reads "How each criterion narrows the cohort". Step labels start with "+ ",
   "− " (U+2212) or "+ tested negative: " by the criterion's mode. "∧" appears nowhere in the UI.
5. The answer heading reads the cohort name, or "Your cohort" when the name is blank.
6. A one-line muted footnote under the cards says what isn't in the data and that the last years
   are partial, with a link-styled button to the Data notes tab.
7. Numbers in the cards and the accrual chart labels use tabular figures.

## Non-goals

- **No output-path or data change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/` or
  `systemd/` changes; no schema, table, column, endpoint or MCP tool changes. Every number shown
  is the same `CountResult` field shown today, through the same `Count` component, so no new
  small-cell rule is needed. Hiding the Share card and funnel shows *less*. A suppressed count
  still renders as the text `<{min_cell}` in `span.suppressed`, never 0 or blank (pinned in the
  hero, acceptance 6). **`research_id` and `report_id` are not touched.**
- No definition, operations-model, share-link, `transport.ts` or `api.gen.ts` change.
- No chart change beyond `tabular-nums` on `.barlabel`. Bar heights, the year grid, partial-year
  markers and gap years are item 4 (#100).
- No guided start or example cohorts on the empty definition (item 6, #102). This item only hides
  the Share card and funnel there; the Patients and Accrual cards, footnote and tabs still show.
- The Compare table's "Accrual a year" row (`Compare.tsx:36-37`, pinned at `compare.test.tsx:57`)
  and the feasibility statement's "(about x.x a year)" (`cohort.ts` `feasibility`) keep
  `toFixed(1)`. Both belong to item 7 (#103), which can switch them to `fmtPerYear` from this item.
- No builder change: criterion card labels keep `criterionLabel` with its "no" prefix (item 5,
  #101). The Loosen box keeps "Drop {criterionLabel}".
- No new dependency, web font, CDN, `index.html`, `vite.config.ts` or CSP change.

## Design

All changes are in `web/src/` plus one paragraph in `dashboard/COHORT_DISCOVERY.md`.

### `web/src/cohort.ts` (two helpers in the `// --- numbers` section)

The issue's file list names `Answer.tsx`, `styles.css` and `answer.test.tsx`. These two pure
helpers go in `cohort.ts` instead of `Answer.tsx` because that is where the number and definition
helpers live and are unit-tested, and items 6 (#102, guided start: "when the definition has no
population filters and no criteria") and 7 (#103, Compare and statement precision) need the same
two rules.

```ts
/** Patients a year for display: one decimal below 10, whole numbers (with separators) from 10. */
export function fmtPerYear(perYear: number): string {
  const tenth = Math.round(perYear * 10) / 10;
  return tenth < 10 ? tenth.toFixed(1) : Math.round(perYear).toLocaleString("en-US");
}

/** True when the definition has no population value, no year window and no criteria. */
export function isEmptyDefinition(d: Definition): boolean {
  return d.criteria.length === 0 && d.population.years == null && POP_DIMS.every((k) => d.population[k].length === 0);
}
```

`isEmptyDefinition` ignores `name`, `scope`, `breakdown` and `pivot`: those don't change who is
counted. Rounding to tenths first means 9.96 renders "10", not "10.0".

### `web/src/Answer.tsx`

Imports add `fmtPerYear` and `isEmptyDefinition` from `./cohort.ts` (and `Criterion` from
`./types.ts` if the spread below needs the cast).

**`stepLabel(d: Definition, i: number, criterion: string | null): string`** (same signature):

```ts
if (i === 0 || criterion == null) return populationLabel(d.population);
const c = d.criteria.find((x) => x.id === criterion);
if (!c) return `+ ${criterion}`;
const label = criterionBody(c);
return c.mode === "exclude" ? `− ${label}` : c.mode === "tested_negative" ? `+ tested negative: ${label}` : `+ ${label}`;
```

`criterionBody(c)` (new export in `cohort.ts`; `criterionLabel` is now the body plus the "no" mode
word) is what the criterion matches without any mode word, so the mode word appears once, in the
prefix: "− KEAP1 alteration", not "− no KEAP1 alteration", and "+ tested negative: STK11
alteration", not "+ tested negative: STK11 tested negative". For a tested-negative alteration the
genes are joined with " and " (every listed gene must be negative; include and exclude join with
" or ", any one gene): "+ tested negative: STK11 and KEAP1 alteration", matching the builder card's
"STK11 and KEAP1 tested negative". The minus is U+2212, not a hyphen.

**`Cards({r, d, options})`** (same props). `d` is the counted definition, as today.

```tsx
const window = d.population.years ?? options?.years ?? null;
const perYear = accrualPerYear(r.patients, window);
const share = pct(r.patients, r.denominator);
return (
  <div className="cards">
    <div className="card hero">
      <h3>Patients</h3>
      <p className="big"><Count n={r.patients} minCell={r.min_cell} /></p>
      <p className="sub">{/* reports line, unchanged */}</p>
    </div>
    <div className="card">
      <h3>Accrual</h3>
      <p className="big">{perYear == null ? "–" : fmtPerYear(perYear)}</p>
      {window && <p className="sub">per year, {window[0]}–{window[1]}</p>}
      {perYear != null && <p className="sub"><TierPill perYear={perYear} /></p>}
    </div>
    {!isEmptyDefinition(d) && <div className="card">{/* Share of population, unchanged */}</div>}
  </div>
);
```

- The window line shows whenever a window is known, including when the count is suppressed
  (the window is not a count). The en dash is U+2013, as in `populationLabel`.
- The Share card's content (`Share of population`, `pct`, "of {Count} patients in {pop}" or
  "(all patients)") is unchanged; it is only wrapped in the emptiness test.

**`Funnel`**: the `<h3 id="funnel-h">` text becomes `How each criterion narrows the cohort`.
Bars, numbers and the legend are unchanged.

**`DataFootnote`**: a new local component under the cards:

```tsx
export const DATA_FOOTNOTE = "Not in this data: stage, treatment, outcomes, race and ethnicity. "
  + "Dates are shifted for de-identification; the last years are partial.";

function DataFootnote({onTab}: {onTab: (t: Tab) => void}) {
  return <p className="hint footnote">{DATA_FOOTNOTE}{" "}
    <button type="button" className="btn-tertiary" onClick={() => onTab("Data notes")}>More in Data notes</button></p>;
}
```

The "absent" sentence restates the server's `NOTES["absent"]` (`cohort/definition.py`), which the
Data notes tab still shows verbatim; it is a client constant rather than `r.notes.at(-1)` because
nothing pins the order of `notes`. The second sentence is the owner's 2026-10-30 copy.

**`Answer`** body order becomes: live region, `Cards`, `DataFootnote`, `Loosen`, then the funnel
only when the counted definition is not empty:

```tsx
<Cards r={r} d={counted} options={options} />
<DataFootnote onTab={onTab} />
<Loosen r={r} d={counted} stale={stale} onOp={onOp} />
{!isEmptyDefinition(counted) && <Funnel r={r} d={counted} />}
```

**Heading**: `<h2 id="answer-h" tabIndex={-1}>{definition.name.trim() || "Your cohort"}</h2>`.
It reads the *current* definition's name (the one in the header input), so a rename shows at once
even while the answer is recounting. `id`, `tabIndex` and `main aria-labelledby="answer-h"` stay,
so the summary bar's "View" link (`App.tsx` `SummaryBar`) still lands on it.

### `web/src/styles.css`

In the `/* answer */` block:

```css
.cards { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: var(--s3); margin-bottom: var(--s2); }
.big { font-size: var(--fs-2xl); line-height: var(--lh-2xl); font-weight: 600; font-variant-numeric: tabular-nums; }
.card.hero .big { font-size: var(--fs-hero); line-height: var(--lh-hero); }
.footnote { margin: 0 0 var(--s4); }
.footnote .btn-tertiary { min-height: 0; padding: 0; font-size: inherit; }
```

`.barlabel` gains `font-variant-numeric: tabular-nums;`. Inside the existing
`@media (max-width: 600px)` block:

```css
.card.hero { grid-column: 1 / -1; }
```

The two-column grid goes in its own media query placed *after* the base `.cards` rule, because the
existing 600px block sits earlier in the file and has the same specificity, so the later base
`2fr 1fr 1fr` would win there:

```css
@media (max-width: 600px) { .cards { grid-template-columns: 1fr 1fr; } }
```

With the Share card hidden the third track stays empty, so the hero keeps about half the row.
No new tokens, no raw hex (`styles.test.ts` already pins both).

### `dashboard/COHORT_DISCOVERY.md` §3.3 "Centre: answer"

The first two bullets describe the cards and the "**Funnel**". Replace them with:

> - Cards: patients as the hero (the largest number on the page), then accrual a year with its
>   year window and the existing tier badge, then the percentage of the right denominator. Under
>   the percentage the card names the denominator ("of 120 NSCLC patients tested since 2023").
>   With an empty definition (no population values and no criteria) the percentage card and the
>   funnel are not shown. A one-line footnote under the cards names the fields that are not in
>   the data and says the last years are partial because dates are shifted (#99).
> - **How each criterion narrows the cohort** (the funnel), an attrition table that reads like a
>   CONSORT diagram: one row for each criterion as it is added, prefixed "+", "−" or "+ tested
>   negative:", with the count after it. This view is what makes the work iterative: the user
>   sees which criterion costs the most patients.

The algebraic "population ∧ c1, then ∧ c2" in the §3.1 data-model sketch describes semantics, not
UI copy, and stays. README, ARCHITECTURE, PLAN and COHORT_TOOL don't describe the answer copy.

## Acceptance criteria

1. [ ] The Patients card has class `card hero`; `.card.hero .big` uses `var(--fs-hero)`, `.big`
       uses `var(--fs-2xl)`, and `--fs-hero` is the largest `--fs-*` token (styles test).
2. [ ] `.big` and `.barlabel` have `font-variant-numeric: tabular-nums` (styles test).
3. [ ] The Accrual card reads "per year, {from}–{to}" from `population.years`, else
       `options.years`; no window line when both are null.
4. [ ] `fmtPerYear`: 2 → "2.0", 9.94 → "9.9", 9.96 → "10", 30 → "30", 1234.4 → "1,234"; the card
       shows "30", not "30.0", for 120 patients over four years.
5. [ ] With `EMPTY` as the counted definition: no "Share of population", no `id="funnel-h"`, no
       `class="funnel"`; Patients, Accrual and the footnote still render. A definition with only a
       population value, only a year window, or only a criterion shows both.
6. [ ] A suppressed patient count renders `<span class="suppressed" …>&lt;5</span>` inside the
       hero card's `.big`, and `&lt;10` when `min_cell` is 10; never `>0<`.
7. [ ] The funnel heading is "How each criterion narrows the cohort"; include, exclude and
       tested-negative steps start "+ ", "− " and "+ tested negative: "; no step contains "− no ";
       no rendered answer contains "∧", and `grep -rn "∧" web/src --include=*.tsx --include=*.ts`
       finds nothing outside `*.test.*`.
8. [ ] The heading is the cohort name; blank or whitespace-only name gives "Your cohort";
       `id="answer-h" tabindex="-1"` is kept.
9. [ ] The footnote text `DATA_FOOTNOTE` renders under the cards with a "More in Data notes"
       `.btn-tertiary` button whose `onClick` is `() => onTab("Data notes")`.
10. [ ] `COHORT_DISCOVERY.md` §3.3 bullets are updated as above.
11. [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes.
       `uv run pytest -q` passes (no Python change). Dashboard check: n/a.
12. [ ] Screenshot (orchestrator, after merge, dev server at 1440 light/dark and 390): the patient
        number is visibly the largest text; no "∧"; empty definition has no Share card or funnel;
        Accrual shows its window.

## Test plan

All tests use synthetic `CountResult` / `Definition` objects built in the test (as
`answer.test.tsx` does today); no API, no `$DATA`, no PHI.

`web/src/answer.test.tsx`:

- Update the two `"∧ ALK fusion"` expectations (lines 52, 92) to `"+ ALK fusion"`.
- `cards` describe:
  - "the hero card holds the patient count": `result()` contains `class="card hero"` followed by
    `<h3>Patients</h3><p class="big">8</p>`.
  - "a suppressed patient count is <5 in the hero" (issue acceptance e):
    `render(result({patients: null, reports: null, denominator: null}))` matches
    `/class="card hero"><h3>Patients<\/h3><p class="big"><span class="suppressed"[^>]*>&lt;5<\/span>/`
    and does not contain `>0<`; same with `min_cell: 10` gives `&lt;10`.
  - "accrual names its window": default render contains `per year, 2023–2026`; with
    `population.years: [2024, 2025]` contains `per year, 2024–2025`; with `options={null}` and no
    population years contains no `per year`.
  - "accrual precision": `result({patients: 120})` over the 2023-2026 options window contains
    `<p class="big">30</p>` and not `30.0`; the existing `2.0` expectation stays.
  - "an empty definition shows no share card and no funnel": render with `d = EMPTY` has no
    `Share of population`, no `funnel-h`, no `class="funnel"`, and has `Patients`, `Accrual`,
    `DATA_FOOTNOTE`. With `{...EMPTY, population: {...EMPTY.population, years: [2024, 2025]}}`,
    and with `{...EMPTY, criteria: [kras]}`, both `Share of population` and `funnel-h` are
    present.
  - The existing "an empty population reads (all patients)" case renders
    `{...def, population: EMPTY.population}`, which keeps its criteria, so the Share card still
    shows and the case passes unchanged.
- `funnel` describe (new):
  - "step prefixes by mode, no ∧": a definition with `kras` (include), an exclude
    (`{...alk, id: "c2", gene: ["KEAP1"], class: [], mode: "exclude"}`) and a tested-negative
    (`{...alk, id: "c3", gene: ["STK11"], class: [], mode: "tested_negative"}`) and a funnel over
    `c1`, `c2`, `c3` renders `+ KRAS G12C`, `− KEAP1 alteration`,
    `+ tested negative: STK11 alteration`; the HTML contains no `∧` and no `− no `.
  - "a tested-negative step lists its genes with and": a tested-negative on `["STK11", "KEAP1"]`
    renders `+ tested negative: STK11 and KEAP1 alteration` and not `STK11 or KEAP1`.
  - "the heading names the narrowing": contains `How each criterion narrows the cohort`.
- `Data notes and the answer heading` describe:
  - "the heading is the cohort name or Your cohort": `{...def, name: "Lung pilot"}` gives
    `<h2 id="answer-h" tabindex="-1">Lung pilot</h2>`; `name: ""` and `name: "  "` give
    `>Your cohort</h2>`.
  - "the footnote sits under the cards": the HTML contains `<p class="hint footnote">` with
    `DATA_FOOTNOTE` and `>More in Data notes</button>`, and the footnote's index is after the
    hero card's and before `class="tabs"`. The `onClick` is a one-line `onTab("Data notes")`; the
    web tests have no DOM (they use `renderToStaticMarkup`), so it is not click-tested.

`web/src/cohort.test.ts`, `numbers` describe:

- "fmtPerYear": the five values in acceptance 4.
- "isEmptyDefinition": `EMPTY` → true; `EMPTY` with a name, `scope: "report"`, a breakdown or a
  pivot → true; with one `oncotree` value, with `years`, with one criterion → false.

`web/src/styles.test.ts`:

- "the patient count is the largest type": `rule(".card.hero .big")` contains `var(--fs-hero)`;
  `rule(".big")` contains `var(--fs-2xl)` and `tabular-nums`; `rule(".barlabel")` contains
  `tabular-nums`; `parseInt(light["--fs-hero"])` is greater than every other `--fs-*` token.
- The mobile-block test gains: `.card.hero` has `grid-column: 1 / -1`.

## Risks

- **Tier and rounded number can disagree at the boundary.** 9.96 a year shows "10" with the
  "Low / pilot" pill (`tierFor` uses the unrounded value). Same class of mismatch exists today
  with "10.0". Accept; the pill's title states the thresholds.
- **Copy drift.** `DATA_FOOTNOTE`'s first sentence restates the server's `absent` note. If the
  server adds an absent field, the footnote lags until edited; the Data notes tab stays correct.
- **Precision differs across views until #103.** The card shows "30" while Compare and the
  statement show "30.0". Accepted for scope; #103 switches them to `fmtPerYear`.
- **Merge overlap with #100/#101** in `styles.css` (`.barlabel`, the 600px block) and
  `answer.test.tsx`. Small and textual; the later PR rebases.
- **Accessibility of "−".** Screen readers read U+2212 as "minus", which is the intended reading
  ("minus patients with KEAP1 alteration"); the review rejected "∧" for reading as "logical and".
- The heading now changes with the cohort name, so `main`'s accessible name changes too. It is
  still unique and focusable; the "View" link targets the `id`, not the text.
