# Spec #100: UI accrual and funnel charts (no scroll, one baseline, suppressed bar height, gap years)

Issue #100 is item 4 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, §1.4,
§2 "Suppressed rule" and wireframes, §3 item 4). It depends on #97 (tokens, merged) and follows
#99 (answer hierarchy, merged). It also carries the #105 follow-up from the #97 review: the "<5"
text in hatched table cells must reach 4.5:1 in both themes, and every `font-size` outside `:root`
must be a `--fs-*` token. All changes are in `web/src/` plus one bullet in
`dashboard/COHORT_DISCOVERY.md`.

## Goal

1. The accrual chart never scrolls: N years are N equal grid columns that always fit the answer
   column. When N > 12 the year labels are two-digit (`’15`).
2. Every bar sits on one baseline: the label row has a fixed height of two lines (count, year).
   A partial year is marked by its lighter bar and a `*` after its year label, with one legend
   line "* partial year", not a third label line.
3. Years with no patients between the first and last listed year get an empty slot whose count
   label is "–" (U+2013), with the legend line "–: no patients that year". The `sr-only` table
   lists them as "no patients".
4. A suppressed bar is drawn at the height a count of `min_cell` would have
   (`max(2%, min_cell / max)`), in the accrual chart and the funnel, so a hatched bar is never
   taller (or longer) than a shown bar of `min_cell` or more.
5. When every listed year is suppressed, the chart collapses to one hatched strip reading
   "Every year under {min_cell} or hidden".
6. (#105) Suppressed `<5` text in a hatched `td` / `.summary-count` meets 4.5:1 in light and
   dark; every `font-size` outside `:root` is `var(--fs-*)`. Both pinned in `styles.test.ts`.

## Non-goals

- **No output-path or data change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/src`
  or `systemd/` changes; no schema, table, column, endpoint, MCP tool, `transport.ts` or
  `api.gen.ts` change. The chart reads the same `CountResult.by_year`, `funnel` and `min_cell`
  it reads today. **`research_id` and `report_id` are not touched.**
- No definition, operations-model or share-link change.
- No funnel layout change beyond bar length (the 600px stacked funnel, §2.12, is not this item).
- No Compare, Breakdown or Pivot change other than the `td.hatched` stripe mix (item 7, #103).
- No guided-start sparkline (item 6, #102).
- No new dependency, chart library, web font, CDN, `index.html` or `vite.config.ts` change.

## Privacy

This changes an output view, so the issue carries `review:security`. What the page can show is
unchanged:

- **Suppressed counts** still render as `Count` (`<span class="suppressed">&lt;{min_cell}</span>`)
  plus a hatch, never 0 or blank. The new hatched height is a function of `min_cell` and the
  largest *shown* count only, both already on the page, so it carries no information about the
  hidden value (today's fixed 12% / 8% carries none either; the new rule fixes the visual
  ordering, not the disclosure).
- **Gap years.** `by_year` comes from `GROUP BY yr` over the cohort (`cohort/compile.py`), so a
  year is listed only if it has at least one patient, and every listed count is floored to
  `min_cell` or more or `null` (`suppress.floor`). A year missing between the first and last
  listed years therefore has a true count of 0. That is visible today as a missing bar, and
  Compare already says "Blank: no patients that year" (`Compare.tsx`). The slot is drawn only
  between the first and last listed year, never extended to the options window. A gap is always
  "–", never "<5" and never hatched; a `null` year is always "<5" and hatched, never "–".
- **All-suppressed strip.** A year can be `null` by secondary suppression (hidden so a small
  year cannot be worked out by subtraction from `patients`), so "every year under 5" can be
  false: two years of 3 and 7 patients are both `null`. The strip therefore reads
  "Every year under {min_cell} or hidden", and the hatched legend line explains the hatch, as
  everywhere else. This deliberately extends the issue's copy ("Every year under {min_cell}") so
  the sentence stays true. The sr-only table still lists every year as `<5`.

## Design

### `web/src/types.ts`

Add, next to `CountResult`:

```ts
export type YearCount = S["YearCount"];
```

### `web/src/cohort.ts` (two helpers in the `// --- numbers` section, after `isEmptyDefinition`)

```ts
/** Bar length in percent of `max` (the largest shown count, at least 1). A suppressed count is drawn
 *  as if it were `minCell`, so it is never longer than a shown bar of `minCell` or more; 0 is no bar. */
export function barPct(n: number | null, max: number, minCell: number): number {
  if (n === 0) return 0;
  return Math.min(100, Math.max(2, ((n ?? minCell) / max) * 100));
}

/** Every year from the first listed to the last: `row` is null for a year the API did not list (no patients). */
export function yearSlots(byYear: readonly YearCount[]): {year: number; row: YearCount | null}[] {
  if (byYear.length === 0) return [];
  const at = new Map(byYear.map((y) => [y.year, y]));
  const years = byYear.map((y) => y.year);
  const first = Math.min(...years);
  return Array.from({length: Math.max(...years) - first + 1}, (_, i) => ({year: first + i, row: at.get(first + i) ?? null}));
}
```

The 2% floor is shared by shown and suppressed bars; with a different floor for each, a hatched
bar could again be taller than a small shown one. The `Math.min(100, …)` only matters for a funnel
whose top step is hidden while a later one is shown (see `Funnel`).

`cohort.ts` imports `YearCount` from `./types.ts`.

### `web/src/Answer.tsx`

Imports add `barPct` and `yearSlots` from `./cohort.ts`.

**`Funnel`**: replace `top` with the largest shown step and draw every bar through `barPct`:

```tsx
const max = Math.max(1, ...r.funnel.map((s) => s.patients ?? 0));
…
<span className="track" aria-hidden="true">
  <span className={s.patients == null ? "bar hatched" : "bar"} style={{width: `${barPct(s.patients, max, r.min_cell)}%`}} />
</span>
```

The funnel is non-increasing, so `max` equals the first step whenever it is shown. A shown step's
floor moves from 1% to 2% (the shared floor). A known 0 is still `width:0%`. The legend is
unchanged.

**`AccrualTab`** is rewritten:

```tsx
const ACCRUAL = "Patients by year of first qualifying report";

function AccrualTab({r}: {r: CountResult}) {
  const slots = yearSlots(r.by_year);
  if (slots.length === 0) return <p>No years to show.</p>;
  const max = Math.max(1, ...r.by_year.map((y) => y.patients ?? 0));
  const allHidden = r.by_year.every((y) => y.patients == null);
  const short = slots.length > 12;
  const partial = r.by_year.some((y) => !y.complete);
  const gap = slots.some((s) => s.row == null);
  const hidden = r.by_year.some((y) => y.patients == null);
  return (
    <div>
      <figure className="accrual">
        {allHidden
          ? <p className="strip"><span className="bar hatched" aria-hidden="true" /><span>{`Every year under ${r.min_cell} or hidden`}</span></p>
          : <div className="bars" role="group" aria-label={ACCRUAL}>
              {slots.map(({year, row}) => (
                <div key={year} className={row == null ? "col gap" : row.complete ? "col" : "col partial"}>
                  <div className="barbox" aria-hidden="true">
                    {row && <div className={row.patients == null ? "vbar hatched" : "vbar"}
                      style={{height: `${barPct(row.patients, max, r.min_cell)}%`}} />}
                  </div>
                  <div className="barlabel" aria-hidden="true">
                    <span>{row ? <Count n={row.patients} minCell={r.min_cell} /> : "–"}</span>
                    <span>{`${short ? `’${String(year).slice(-2)}` : year}${row && !row.complete ? "*" : ""}`}</span>
                  </div>
                </div>
              ))}
            </div>}
        <figcaption>{ACCRUAL}</figcaption>
      </figure>
      {(partial || gap || hidden) && <p className="legend">
        {partial && !allHidden && <span>* partial year</span>}
        {gap && !allHidden && <span>–: no patients that year</span>}
        {hidden && <span><span className="swatch hatched" aria-hidden="true" /> {`<${r.min_cell}`}: {SUPPRESSED.toLowerCase()}.</span>}
      </p>}
      <table className="sr-only">
        <caption>{ACCRUAL}</caption>
        <thead><tr><th scope="col">Year</th><th scope="col">Patients</th><th scope="col">Complete</th></tr></thead>
        <tbody>{slots.map(({year, row}) => (
          <tr key={year}><th scope="row">{year}</th>
            {row
              ? <><td><Count n={row.patients} minCell={r.min_cell} /></td><td>{row.complete ? "yes" : "partial year"}</td></>
              : <><td>no patients</td><td>unknown</td></>}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
```

Notes for the implementer:

- The year label is **one template string** so the static markup is `<span>2025*</span>`, not
  two text nodes. `’` is U+2019; "–" is U+2013 (the dash already used in `Cards`).
- `tabIndex={0}` comes off `.bars`: it existed so a keyboard user could scroll the overflowing
  chart, and nothing scrolls now. `role="group"` and its `aria-label` stay.
- A gap row's "Complete" cell is "unknown": `year_complete` is only returned for listed years.
- The empty case (`by_year` is `[]` whenever `patients` is `null` or 0, or no report is dated)
  replaces today's empty box with "No years to show."; it shows no count.
- The legend `<p>` is rendered only when it has at least one line; in the all-hidden case only
  the hatched line can show (the strip replaces the year slots, so "*" and "–" have nothing to
  mark). `partial` / `gap` therefore also check `!allHidden`; if both are false and `hidden` is
  true the `<p>` holds one span.

### `web/src/styles.css`

Replace the accrual block (today `.accrual .bars` … `.barlabel`):

```css
.accrual .bars { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: var(--s1); height: 12rem; }
.accrual .col { display: grid; grid-template-rows: minmax(0, 1fr) calc(2 * var(--lh-xs)); min-width: 0; }
.accrual .barbox { display: flex; align-items: flex-end; min-height: 0; }
.vbar { width: 100%; background: var(--bar); border-radius: 2px 2px 0 0; }
.col.partial .vbar:not(.hatched) { background: var(--bar-partial); }
.barlabel { font-variant-numeric: tabular-nums; display: flex; flex-direction: column; align-items: center; white-space: nowrap; font-size: var(--fs-xs); line-height: var(--lh-xs); }
.accrual .strip { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: var(--s3); margin: 0; }
.accrual .strip .bar { height: var(--s4); }
```

- `grid-auto-flow: column` with `grid-auto-columns: minmax(0, 1fr)` gives N equal columns
  without passing N from JSX. No `overflow-x`, no `min-width` in rem on `.col`, so it always fits.
- The fixed second row (`calc(2 * var(--lh-xs))`) is the one baseline: every `barbox` has the
  same height whatever its label says.

Legend items: `.legend` gains `flex-wrap: wrap;` and a new rule

```css
.legend > span { display: inline-flex; align-items: center; gap: .4rem; margin-right: var(--s3); }
```

(the funnel legend is a bare text node plus a swatch, so it is unaffected).

**#105 contrast.** In `td.hatched, .summary-count.hatched` change the stripe mix from 35% to
15%: `color-mix(in srgb, var(--suppressed-stripe) 15%, transparent)`. Composited over
`--suppressed-bg`, the stripe is about `#dfe3e7` (light) and `#2b3038` (dark), giving `--muted`
text about 4.74:1 and 4.56:1 (35% gives about 3.98 and 3.69). The bar/swatch hatch
(`.bar.hatched, .vbar.hatched, .swatch.hatched`) carries no text and keeps the full stripe.

**#105 font sizes.** Delete `font-size: inherit;` from `.footnote .btn-tertiary`: the base
`button { font: inherit; }` rule already inherits it and nothing else sets a button font size.
The rule becomes `.footnote .btn-tertiary { min-height: 0; padding: 0; }`.

### `dashboard/COHORT_DISCOVERY.md` §3.3 "Centre: answer", the *Accrual* tab bullet

Replace with:

> - *Accrual*: patients by year of first qualifying report, one equal column per year from the
>   first to the last, so the chart never scrolls (two-digit year labels past 12 years). Years
>   under 5 are drawn as a hatched "<5" bar at the height a count of 5 would have, never taller
>   than a shown bar. A year with no patients between the first and last is an empty "–" slot.
>   Partial years (the current year and date-shift spillover) are shaded and marked "*". When
>   every year is hidden the chart is one hatched strip. Each mark has a legend line.

README, ARCHITECTURE, PLAN and COHORT_TOOL don't describe the chart.

## Acceptance criteria

1. [ ] (a) `.accrual .bars` uses `grid-auto-columns: minmax(0, 1fr)` and has no `overflow`;
       `.accrual .col` has no rem `min-width` (styles test). With 14 synthetic years the bar
       labels are `’10` … `’23` and no `barlabel` contains a four-digit year; with 12 they are
       four-digit. The sr-only table always has the four-digit year.
2. [ ] (b) `.accrual .col` has `grid-template-rows: minmax(0, 1fr) calc(2 * var(--lh-xs))`
       (styles test). A partial year renders `<span>2025*</span>` in its `barlabel`, no
       `barlabel` contains "partial year", and the legend has "* partial year". The sr-only
       table still says "partial year".
3. [ ] (c) `barPct(null, max, m) <= barPct(n, max, m)` for every `n` from `m` to `max`, over
       synthetic `max` in {5, 10, 400, 10000} and `m` in {5, 10}; `barPct(null, 50, 5) === 10`;
       `barPct(0, 50, 5) === 0`; `barPct(3, 10000, 5) === 2`; never above 100. In a rendered
       accrual chart and funnel, each hatched bar's height/width is ≤ that of every shown bar
       with a count ≥ `min_cell`.
4. [ ] (d) `yearSlots` fills every missing year between first and last with `row: null` and adds
       none outside; a rendered chart with years 2020 and 2022 has a 2021 slot
       (`class="col gap"`), the legend "–: no patients that year", and the sr-only row
       `<th scope="row">2021</th><td>no patients</td><td>unknown</td>`. No gap → no "–" legend.
5. [ ] (e) A `null` year renders `<div class="vbar hatched" …>` and `&lt;5` in its `barlabel`,
       never `>0<` and never an empty `<span></span>`. A gap slot's markup contains "–", no
       `&lt;5` and no `hatched`.
6. [ ] All-`null` `by_year` renders the `.strip` with `.bar.hatched` and
       "Every year under 5 or hidden" (`10` when `min_cell` is 10), no `class="bars"`, the
       hatched legend line, and an sr-only row per year reading `&lt;5`. Empty `by_year`
       renders "No years to show." and no chart.
7. [ ] The funnel's hatched bar width is `barPct(null, max, min_cell)` (e.g. `width:10%` for a
       synthetic top step of 50 and `min_cell` 5); a known 0 is still `width:0%`.
8. [ ] (#105) `styles.test.ts` computes `--muted` against the `td.hatched` stripe (mix parsed
       from the rule, composited over `--suppressed-bg`) and against `--suppressed-bg`, and
       requires ≥ 4.5:1 in both themes; it passes at 15% and would fail at 35%.
9. [ ] (#105) `styles.test.ts` asserts every `font-size` value outside the `:root` blocks matches
       `var(--fs-…)`.
10. [ ] `COHORT_DISCOVERY.md` Accrual bullet is updated as above.
11. [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes.
        `uv run pytest -q` passes (no Python change). Dashboard check: n/a.
12. [ ] Screenshot (orchestrator, after merge, dev server at 1440 light/dark): every year visible
        without scrolling (01); one baseline including partial years (08); no hatched bar taller
        than a shown bar of 5 or more (01); no year missing from the axis (06/08).

## Test plan

All tests build synthetic `CountResult` objects in the test (as `answer.test.tsx` does); no API,
no `$DATA`, no PHI. Synthetic counts only (e.g. 6, 7, 400).

**`web/src/cohort.test.ts`**, `describe("numbers")`:

- `barPct`: the property loop in acceptance 3, plus the four fixed values.
- `yearSlots`: `[]` → `[]`; `[2020, 2022]` → years `[2020, 2021, 2022]` with `row` null only for
  2021; unsorted input `[2022, 2020]` gives the same; a single year gives one slot.

**`web/src/answer.test.tsx`**, a new `describe("accrual chart")` (the existing
`tabs › accrual` test keeps passing; the fixture's 2025 is partial and 2024 is `null`):

- null year (acceptance 5): isolate a column by splitting the markup on `<div class="col` and
  picking the part containing `<span>2024</span>`; assert `vbar hatched`, `&lt;5`, no `>0<`, no
  `<span></span>`. Gap columns are isolated the same way.
- gap year (acceptance 4/5): `by_year` 2020 (6) and 2022 (7); assert the exact gap column
  `<div class="col gap"><div class="barbox" aria-hidden="true"></div><div class="barlabel" aria-hidden="true"><span>–</span><span>2021</span></div></div>`,
  the legend text, the sr-only row, and that the gap part has no `&lt;5` and no `hatched`.
- partial year (acceptance 2): `<span>2025*</span>`, "* partial year" in the legend, and no
  `barlabel` block contains "partial year".
- two-digit labels (acceptance 1): 14 years 2010–2023 → `<span>’10</span>`, no
  `<span>2010</span>` inside a `barlabel`, `<th scope="row">2010</th>` in the table; 12 years →
  `<span>2010</span>`.
- heights (acceptance 3): `by_year` 2020 (5), 2021 (`null`), 2022 (400): parse every
  `height:([\d.]+)%`; the hatched one ≤ the 2020 one. Funnel: `funnel` 50, 5, `null` →
  `class="bar hatched" style="width:10%"`, and ≤ the width of the step of 5.
- all hidden and empty (acceptance 6).

**`web/src/styles.test.ts`**:

- New `test("accrual: equal columns, no scroll, one label row")` for acceptance 1–2 using the
  existing `rule()` helper on `.accrual .bars` and `.accrual .col`.
- New `test("<5 text on a hatched cell meets 4.5:1 in both themes")`: parse the percent from
  `rule("td.hatched")` (`/suppressed-stripe\) (\d+)%/`), mix
  `round(p * stripe + (1 - p) * bg)` per sRGB channel into `#rrggbb`, and check `contrast()` of
  `--muted` on that and on `--suppressed-bg`, per theme.
- New `test("every font-size outside :root is a --fs-* token")`: every
  `/font-size:\s*([^;}]+)/g` match in `css.replace(ROOT, "")` matches
  `/^var\(--fs-[\w-]+\)$/`, and there are more than five matches.
- Update the mobile-shell test's `suppressed-stripe\) 35%` regex to `15%`.

Run: `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`; `uv run pytest -q`.

## Risks

- **Crowded labels at large N.** Equal columns at about 840px share the answer column; past
  roughly 25 years a four-character count ("1,234") can be wider than its column and overlap its
  neighbour. Labels are not clipped (a clipped count would misread). The sr-only table and the
  `Count` title carry the values. Real year spans are well under that today; if they grow, label
  every other count, a follow-up.
- **Lighter cell hatch.** At 15% the table-cell stripe is quieter. Hatching stays visible in
  greyscale and the italic "<5" still marks the cell; bars and swatches keep the full stripe.
  Dark mode passes with a small margin (about 4.56:1); the new test pins it, so a later token
  change that breaks it fails CI.
- **Copy deviation.** "Every year under {min_cell} or hidden" extends the issue's wording so it
  stays true under secondary suppression (see Privacy).
- **Wide single columns.** With one to three years each bar fills its column, as today; not
  changed here.
