# Spec #103: UI panels and tabs (Feasibility, Compare, Breakdown, Pivot)

Issue #103 is item 7 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`: §1
items 2.4, 2.8, 2.9, 2.10, 2.11 and 3.8; §2 "Controls"; §3 item 7). It changes `web/` only, plus two
bullets of `dashboard/COHORT_DISCOVERY.md` §3.3. It depends on #97 (tokens and base controls) and
#98 (layout shell), both merged.

## What is already done

Earlier items already cover part of this issue. Keep this work and don't redo it:

- `textarea` is in the `font: inherit` rule (#97), so the statement is no longer monospace.
- The header's Compare button is disabled when there is one version and shows "Make a change to
  compare versions" (`App.tsx`, `id="compare-why"`, #98).
- The answer footnote `DATA_FOOTNOTE` already says "Dates are shifted for de-identification; the
  last years are partial." (#99).

## Goal

1. **Tabs** (Accrual, Breakdown, Pivot, Data notes) are text with a 2px accent underline on the
   selected tab. They have no box, no fill and no rounded corners, and the strip scrolls sideways
   when it is too narrow. The arrow-key handling (`onKey` in `Answer`) is unchanged.
2. **Feasibility panel** is a floating layer anchored under the header, so the page below doesn't
   move. It has:
   - a heading, "Feasibility statement for grant text";
   - the read-only textarea in a block 65ch wide;
   - **Copy** as the only filled (`btn-primary`) button;
   - Close (secondary).

   Focus moves to the heading when the panel opens, Escape closes it, and closing it returns focus
   to the button that opened it.
3. **Statement copy for future years** (owner decision, review §2.10: copy, not clamping). When the
   statement names a year window, it also says "Collection dates are shifted for de-identification,
   so the last years are partial."
4. **Compare**: the "Count" button becomes "Compare selected". When the history has only one
   version, the panel shows explanatory text in place of the checkboxes and the button.
5. **Breakdown**: a purpose line, and the eight checkboxes become toggle chips (`aria-pressed`
   buttons).
6. **Pivot**:
   - a purpose line;
   - the selects' empty option reads "Choose…" (not "none") and the selects are at most 16rem wide;
   - with no pivot chosen, three suggested pairs ("Tumor type × Year", "Vendor × Year", "Tumor type
     × Sex") call the existing `choose()`.
7. Closing the Share and Compare panels also returns focus to their trigger, through the same
   `closePanel`. Review §3.8 asks for this for both disclosed panels, and it costs one shared
   function.

## Non-goals

- **No new output path and no data change.** Nothing under `src/uccc_genomics/`, `mcp/`,
  `dashboard/src/` or `systemd/` changes. No schema, table, column, endpoint or MCP tool changes,
  and `api.gen.ts` / `openapi.json` are unchanged.
  - Every count still comes from the existing `/api/cohort` and `/api/pivot` calls, with their
    floor, neighbour checks and secondary suppression.
  - Every count renders through the existing `Count` component: `null` is "<5" in
    `span.suppressed`, and table cells keep `td.hatched`.
  - The pivot suggestions are constant UI strings that set `d.pivot` through the existing
    `set_pivot` operation. They show no counts.
  - The new statement sentence is a constant with no digits.
  - **`research_id` and `report_id` are not touched.**
- The definition and operations model, the share-hash format, `transport.ts`, the builder, the
  header layout, `SummaryBar`, `Start`, the Accrual chart and the funnel don't change.
- No clamping of years. The owner chose copy (review §2.10).
- Share and Compare stay in normal page flow. Only the Feasibility panel floats; the issue asks for
  anchoring on Feasibility only. Compare's results table can be wide, and in flow it scrolls inside
  `GridTable`.
- No "pick at least two" hint inside Compare. The issue asks only for the single-version text, and
  the default selection is already the last two versions.
- No new dependency and no DOM emulator. Tests use `bun test`, `renderToStaticMarkup`, direct calls
  to exported functions and source-text checks, as #102 and #104 did.
- No raw hex colours outside `:root`, and every `font-size` is a `--fs-*` token. `styles.test.ts`
  already enforces both.

## Design

Files:

- `web/src/App.tsx`, `web/src/Compare.tsx`, `web/src/Answer.tsx`, `web/src/cohort.ts`,
  `web/src/styles.css`;
- tests: `web/src/app.test.tsx`, `web/src/compare.test.tsx`, `web/src/answer.test.tsx`,
  `web/src/cohort.test.ts`, `web/src/styles.test.ts`;
- docs: `dashboard/COHORT_DISCOVERY.md`.

### `web/src/cohort.ts`: one sentence in `feasibility()`

In `feasibility(d, r, years)`, after the report-scope sentence and before the " Counts are
distinct…" sentence, add:

```ts
if (years) text += " Collection dates are shifted for de-identification, so the last years are partial.";
```

Add it only when `years` is non-null, because then the statement names a window ("Between {from} and
{to}, …") whose last year can be in the future. With `years === null` the statement says "To date,"
and claims no year. The sentence has no digits, so the existing "every number is from the result,
the years or the definition" test keeps its expected list.

This puts the sentence in the copied grant paragraph itself, not only in a hint next to it. The
problem in §2.10 is that the *grant text* names a year that hasn't happened yet, and a hint next to
the textarea would not travel with the copied text.

### `web/src/App.tsx`

**`focusTrigger`** (new export, above `App`):

```ts
/** Focus back on the button that opened a panel, or on ⋯ when that button sits in the closed mobile menu (hidden). */
export function focusTrigger(trigger: HTMLElement | null, more: HTMLElement | null): void {
  (trigger && trigger.offsetParent !== null ? trigger : more)?.focus();
}
```

`offsetParent` is `null` when the element or an ancestor has `display: none`, which is the state of
`.actions` at 600px and below while the ⋯ menu is closed. `togglePanel` closes the menu.

**Trigger refs and `closePanel`** in `App`:

```ts
const shareRef = useRef<HTMLButtonElement>(null);
const compareRef = useRef<HTMLButtonElement>(null);
const feasibilityRef = useRef<HTMLButtonElement>(null);
const closePanel = () => {
  if (panel) focusTrigger({share: shareRef, compare: compareRef, feasibility: feasibilityRef}[panel].current, moreRef.current);
  setPanel(null);
};
```

- Put `ref={shareRef}`, `ref={compareRef}` and `ref={feasibilityRef}` on the three header buttons.
- Pass `onClose={closePanel}` to `SharePanel`, `Compare` and `FeasibilityPanel`. They pass
  `() => setPanel(null)` today.
- Don't change the header markup otherwise. The header test that counts one `btn-primary` and the
  test that no `cohort_id` appears in the header source must keep passing.

**Anchor for the Feasibility panel.** Wrap the Feasibility panel in a zero-height anchor right after
`</header>`:

```tsx
{panel === "feasibility" && (
  <div className="panel-anchor">
    <FeasibilityPanel statement={statement} copied={statementCopied} onCopy={copyStatement}
      onClose={closePanel} textareaRef={statementRef} />
  </div>
)}
```

The Share and Compare blocks stay where they are, with `onClose={closePanel}`.

**`FeasibilityPanel`**: same props as today. New markup:

```tsx
export function FeasibilityPanel({statement, copied, onCopy, onClose, textareaRef}: { /* unchanged */ }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);   // a floating layer takes focus when it opens
  return (
    <section aria-labelledby="feasibility-h" className="panel floating"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <h2 id="feasibility-h" tabIndex={-1} ref={headingRef}>Feasibility statement for grant text</h2>
      {statement === ""
        ? <p role="status">Recounting… the statement updates when the count is current.</p>
        : <textarea readOnly aria-label="Feasibility statement" rows={8} value={statement}
            onFocus={(e) => e.currentTarget.select()} ref={textareaRef} />}
      <div className="row">
        <button type="button" className="btn-primary" disabled={statement === ""} onClick={onCopy}>Copy</button>
        {copied && <span role="status">Copied</span>}
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </section>
  );
}
```

`useEffect` and `useRef` are already imported in `App.tsx`.

### `web/src/Compare.tsx`

- Rename the button text from `Count` to `Compare selected`. The `disabled` condition is unchanged.
- When `versions.length < MIN_PICKED`, the panel renders this in place of the fieldset and the
  button row:

  ```tsx
  <p className="hint">Compare needs two or more versions. Make a change to the cohort, then compare the versions here.</p>
  <div className="row"><button type="button" onClick={onClose}>Close</button></div>
  ```

  Close stays, so the panel can always be closed. The header normally prevents opening the panel
  with one version, but `Compare` must not render a lone disabled button if it is mounted that way
  (for example from a history read from storage).
- `CompareTable` is unchanged. Its suppressed cells still render "<5" through `Count`.

### `web/src/Answer.tsx`

**Breakdown tab** (`BreakdownTab`): replace the fieldset of checkboxes with:

```tsx
<p className="hint">Split this cohort by up to four characteristics. Each table gives patients and their share of everyone in the population with that value.</p>
<fieldset className="toggles">
  <legend>Break down by (up to 4)</legend>
  {BREAKDOWN_DIMS.map(({value, label}) => {
    const on = chosen.includes(value);
    return (
      <button key={value} type="button" className="toggle-chip" aria-pressed={on}
        disabled={!on && chosen.length >= 4} onClick={() => toggle(value)}>
        {on && <span aria-hidden="true">✓ </span>}{label}
      </button>
    );
  })}
</fieldset>
{chosen.length >= 4 && <p className="hint">Four chosen: remove one to add another.</p>}
```

`toggle` and the tables are unchanged.

**Pivot tab** (`PivotTab`):

- Add a module constant, exported for the test:

  ```ts
  /** Pivot pairs offered before one is chosen: population axes every definition has (see pivotAxes). */
  export const PIVOT_SUGGESTIONS = [
    {rows: "oncotree", cols: "year", label: "Tumor type × Year"},
    {rows: "vendor", cols: "year", label: "Vendor × Year"},
    {rows: "oncotree", cols: "sex", label: "Tumor type × Sex"},
  ] as const;
  ```

- At the top of the tab, before `.pivot-controls`, add the purpose line `<p className="hint">Count
  patients for every combination of two characteristics, such as tumor type by year.</p>`.
- The empty option of both selects is `<option value="">Choose…</option>`. The value stays `""`,
  so choosing it still clears the pivot through `choose()`.
- Replace the `!d.pivot || !pivot ? <p>Choose rows and columns.</p> : …` branch with:

  ```tsx
  {!d.pivot
    ? <div className="row suggestions">
        <span className="hint">Choose rows and columns, or try:</span>
        {PIVOT_SUGGESTIONS.map((s) => (
          <button key={s.label} type="button" onClick={() => choose(s.rows, s.cols)}>{s.label}</button>
        ))}
      </div>
    : !pivot
      ? <p>The table appears once it is counted.</p>
      : (/* the existing GridTable and legend, unchanged */)}
  ```

  The "Choose rows and columns." string moves into the suggestions line. Suggestions show only while
  no pivot is chosen.

**Tabs**: no markup change. The `role="tablist"` buttons and `onKey` stay as they are. The look
changes in CSS only.

### `web/src/styles.css`

Replace the two `.tabs` rules and the `.panel textarea` rule, and add these rules. All of them use
existing tokens.

```css
.tabs { display: flex; gap: var(--s4); border-bottom: 1px solid var(--line); margin: 1rem 0 .75rem; overflow-x: auto; scrollbar-width: thin; }
.tabs button { flex: none; white-space: nowrap; background: transparent; color: var(--muted); border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding-inline: var(--s1); }
.tabs button:hover:not(:disabled) { background: transparent; color: var(--fg); }
.tabs button[aria-selected="true"] { color: var(--fg); font-weight: 600; border-bottom-color: var(--accent); }

.panel-anchor { position: relative; }
.panel.floating {
  position: absolute; top: 0; right: var(--s4); z-index: 15; width: min(44rem, calc(100% - 2 * var(--s4)));
  padding: var(--s4); background: var(--bg); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 8px 24px rgb(0 0 0 / .12);
}
.panel textarea { width: 100%; max-width: 65ch; resize: vertical; }

.toggles { border: 0; padding: 0; margin: .4rem 0; display: flex; flex-wrap: wrap; gap: var(--s2); }
.toggles legend { padding: 0; margin-bottom: var(--s1); font-weight: 600; }
.toggle-chip { border-radius: 999px; }
.toggle-chip[aria-pressed="true"] { background: var(--surface-2); border-color: var(--accent); font-weight: 600; }
.pivot-controls select { max-width: 16rem; }
```

Notes for the implementer:

- `.panel-anchor` contains only an absolutely positioned child, so it has zero height and the page
  below doesn't move when the panel opens.
- `.panel.floating` (two classes) overrides the in-flow `.panel` padding, border and background.
- `.tabs button:hover:not(:disabled)` is more specific than the base `button:hover:not(:disabled)`,
  so hovering a tab doesn't paint a box.
- The 600px media block needs nothing new: the panel's `width: min(…, calc(100% - 2 * var(--s4)))`
  already fits a phone.

### `dashboard/COHORT_DISCOVERY.md` §3.3

- In the Tabs list:
  - *Breakdown*: "up to four dimensions, chosen with toggle chips; one table each with patients and
    the share of the population".
  - *Pivot*: add "With no pivot chosen it offers suggested pairs (tumor type × year, vendor × year,
    tumor type × sex) (#103)."
- *Feasibility statement* bullet: add "When it names a year window it says collection dates are
  shifted for de-identification, so the last years are partial (#103). It opens as a floating panel
  under the header with Copy as its one primary button."

## Acceptance criteria

- [ ] (a) `FeasibilityPanel` renders:
  - a heading "Feasibility statement for grant text";
  - the read-only textarea;
  - exactly one `btn-primary`, which is Copy;
  - Close.

  `App` renders it inside a `.panel-anchor`, and the CSS gives `.panel.floating` `position:
  absolute` and `.panel-anchor` `position: relative`, so the page below doesn't shift. Close
  (`closePanel`) and Escape return focus to the trigger (`focusTrigger`), or to ⋯ when the trigger
  is hidden.
- [ ] (b) `Compare` with a single version renders the explanatory text and Close. It renders no
  checkbox, no "Compare selected" and no disabled button. With two or more versions the button reads
  "Compare selected", and "Count" appears nowhere.
- [ ] (c) The selected tab is shown by `border-bottom-color: var(--accent)`. `.tabs button` has
  `border: 0`, `border-radius: 0` and a transparent background, and `.tabs` has `overflow-x: auto`.
  The arrow-key handler is unchanged.
- [ ] (d) The Pivot tab with no pivot chosen shows the purpose line and the three suggested pair
  buttons. Each pair is a valid, distinct pair in `pivotAxes(EMPTY)`. With a pivot chosen, no
  suggestions show. The select placeholder option reads "Choose…" and "none" is gone.
- [ ] (e) Every suppressed cell in the Breakdown, Pivot and Compare tables still renders "<5" with
  `.hatched` (Breakdown, Pivot) or in `span.suppressed` (Compare). The existing tests pass unchanged.
- [ ] Breakdown shows its purpose line and `aria-pressed` toggle chips, with no `type="checkbox"`.
  With four chosen, every unchosen chip is disabled and the "Four chosen" hint shows.
- [ ] `feasibility(d, r, [from, to])` contains "Collection dates are shifted for de-identification,
  so the last years are partial." and `feasibility(d, r, null)` does not. The existing feasibility
  tests pass unchanged.
- [ ] No hex colours outside `:root`, and every `font-size` is a token (`styles.test.ts`).
- [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes. Pytest and
  the dashboard check are n/a: no Python, `dashboard/src` or API model changes.

## Test plan

All tests are `bun test` under `web/src/`. They render with `renderToStaticMarkup` or call exported
functions, as the current suites do. No backend runs, and nothing reads `$DATA`.

- **`app.test.tsx`, `describe("FeasibilityPanel")`**: update the two Copy matchers to the new class:
  `/<button type="button" class="btn-primary" disabled="">Copy<\/button>/` and
  `'<button type="button" class="btn-primary">Copy</button>'`. Add:
  - the panel HTML contains `<h2 id="feasibility-h" tabindex="-1">Feasibility statement for grant
    text</h2>`, `class="panel floating"` and `aria-labelledby="feasibility-h"`;
  - the panel HTML holds exactly one `btn-primary`, for both the empty and the non-empty statement.
- **`app.test.tsx`, `describe("focusTrigger")`**: use fake elements
  `{offsetParent: {}, focus: spy}` and `{offsetParent: null, focus: spy}`:
  - a visible trigger is focused and ⋯ is not;
  - a hidden trigger (`offsetParent: null`) focuses ⋯;
  - a `null` trigger focuses ⋯;
  - both `null` is a no-op that doesn't throw.
- **`app.test.tsx`, source check** (the pattern the file already uses):
  - `App.tsx` contains `className="panel-anchor"`;
  - it contains `onClose={closePanel}` exactly three times;
  - it no longer contains `onClose={() => setPanel(null)}`;
  - the `FeasibilityPanel` source contains `e.key === "Escape"`.
- **`compare.test.tsx`, new `describe("Compare")`**: render `<Compare versions={…} transport={{} as
  Transport} years={null} onClose={() => {}} />`:
  - with one version (`{n: 1, definition: EMPTY}`): contains "Compare needs two or more versions",
    contains `>Close</button>`, does not contain `type="checkbox"`, `Compare selected` or
    `disabled=""`;
  - with two versions: contains `>Compare selected</button>` and does not contain `>Count<`.
- **`answer.test.tsx`, `describe("tabs")`**: replace "pivot before choosing" with:
  - `render(result(), "Pivot")` contains the Pivot purpose line, `Choose rows and columns, or try:`,
    `>Tumor type × Year</button>`, `>Vendor × Year</button>` and `>Tumor type × Sex</button>`. It
    contains `<option value="">Choose…</option>` and not `>none</option>`.
  - with `pivot: {rows: "oncotree", cols: "year"}` and a `PivotResult`: no `Tumor type × Year`
    button. Reuse the existing pivot fixture. The fixture's caption contains "×" but not that button
    text.
  - with a chosen pivot and `p === null`: contains "The table appears once it is counted."
  - `PIVOT_SUGGESTIONS`: for each pair, `rows !== cols`, and both values are in
    `pivotAxes(EMPTY).map((a) => a.value)`.
  - Breakdown: `render(result(), "Breakdown")` contains the Breakdown purpose line,
    `aria-pressed="true"` on the Sex chip (`def.breakdown` is `["sex"]`) and `aria-pressed="false"`
    on Vendor. It has no `type="checkbox"`. With `breakdown: ["oncotree", "organ", "sex",
    "age_band"]` every unpressed chip has `disabled=""` and "Four chosen: remove one to add
    another." shows.
  - The existing suppressed-cell tests (`breakdown: null denominator shows <5…`, `pivot: a null cell
    renders <5…`) stay unchanged and pass.
- **`cohort.test.ts`, `describe("feasibility")`**: add one test. With `[2020, 2024]` the text
  contains "Collection dates are shifted for de-identification, so the last years are partial.",
  placed before " Counts are distinct". With `null` it does not contain it. The existing digit test
  stays unchanged.
- **`styles.test.ts`**: add one test "tabs are underlined, panels float, pivot selects are narrow":
  - `rule(".tabs button")` contains `border: 0`, `border-radius: 0` and `background: transparent`;
  - `rule('.tabs button[aria-selected="true"]')` contains `var(--accent)`;
  - `rule(".tabs")` contains `overflow-x: auto`;
  - the CSS no longer contains `6px 6px 0 0`;
  - `rule(".panel-anchor")` contains `position: relative`;
  - `rule(".panel.floating")` contains `position: absolute`;
  - `rule(".panel textarea")` contains `max-width: 65ch`;
  - `rule(".pivot-controls select")` contains `max-width: 16rem`;
  - `rule('.toggle-chip[aria-pressed="true"]')` contains `var(--accent)`.

  Use the file's `rule()` helper. It matches the first rule whose selector starts with the string,
  so put `.tabs {` before `.tabs button {` in the CSS.

## Risks

- **Focus after closing a panel.** `closePanel` restores focus after the close commits, skipping a
  trigger that is hidden or now disabled (the Feasibility button when the cohort was edited while
  the panel was open): ⋯ next, then the answer heading (#125).
- **A floating panel covers the top of the answer column** while it is open. That is the point of
  "anchored", and the panel holds only the statement and buttons. Escape and Close dismiss it and
  return focus. If it covers too much on a phone, a follow-up can drop `.floating` at 600px and
  below (one media rule).
- **`offsetParent` heuristic.** It is `null` for `display: none` ancestors and also for `position:
  fixed` elements. No header trigger is fixed, so the fallback to ⋯ fires only for the closed mobile
  menu.
- **The statement sentence changes the copied grant text** for every user with a year window. The
  owner chose copy over clamping (review §2.10). The sentence has no digits, so it adds no number to
  the statement.
- **Toggle chips replace checkboxes.** Screen readers announce `aria-pressed` buttons as toggle
  buttons ("pressed" or "not pressed"), and a visible ✓ adds a cue that doesn't rely on colour. No
  test or behaviour depends on the checkbox role.
- **Pivot suggestion axes** come from `DIM_AXES` (`BREAKDOWN_DIMS` + `year`), which every definition
  has. If an axis is renamed there, the `PIVOT_SUGGESTIONS` test fails.
