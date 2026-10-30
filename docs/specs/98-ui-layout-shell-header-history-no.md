# Spec #98: UI layout shell (header, history, no assistant column, mobile header and summary bar)

Issue #98 is item 2 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, §1.2,
§2.5, §2.9, §2.12, §2 wireframes, §3 item 2). It depends on #97 (design tokens and `.btn-*`
classes, merged). It reworks the header and the page grid in `web/` only.

## Goal

1. The header reads, left to right: "Discover", the cohort name at `--fs-xl`, ↶/↷ plus a
   **History** select whose options read "Edit n", then a right-aligned group of **Share**,
   **Compare** and **Feasibility statement**. Feasibility statement is the only `.btn-primary` in
   the header.
2. The `cohort_id` leaves the header. It shows as "Cohort ID (for support)" in the Share panel and
   in the Data notes tab.
3. Compare is disabled when there are fewer than two versions, and visible text next to it says
   why.
4. The Assistant column is removed (owner decision, 2026-10-30). The answer column takes its
   width.
5. The page is a 1280px max-width grid, centred.
6. At 600px and below, the header actions sit behind a ⋯ button, the header is at most two rows,
   and a sticky bottom summary bar shows the patient count (`<Count>`, so "<5" and hatched when
   suppressed), the tier pill and a "View" link to the answer.

## Non-goals

- **No ops-model, definition or share-link change.** ↶/↷ and the History select both call the
  existing `setHist({...h, current: i})` and `refresh()`. `pushVersion`, `History`, `HISTORY_KEY`,
  `shareHash`, `readShareHash` and `transport.ts` don't change. Editing from an earlier step still
  appends a new version at the end (there is no redo truncation); ↷ just moves `current` forward.
- No hero card, card copy, funnel, chart, tab, builder, typeahead or guided-start change. Those are
  items 3-6 (#99-#102). The Feasibility and Compare panels keep their markup and their place
  under the header; item 7 (#103) anchors them, adds the heading, makes Copy primary and adds the
  Compare panel's helper text. The Feasibility button stays disabled while there is no current
  answer. Item 7 gives it a visible reason (review 3.4).
- No click-outside or focus-trap behaviour for the ⋯ menu. It closes on ⋯, on Escape and when an
  action in it is chosen. Since #125 it also closes when Tab moves focus out of the header.
- **No data or output-path change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/` or
  `systemd/` changes. No schema, table or column changes. The summary bar shows numbers the answer
  cards already show (the same `CountResult`, through the same `Count` component), so it is not a
  new output path and needs no new small-cell rule. A suppressed count renders as
  the text "<5" (`<` and the result's `min_cell`) inside a hatched span, never 0 or blank. The `cohort_id` was already on
  screen; it moves. **`research_id` and `report_id` are not touched.**
- No new dependency, web font, CDN, `index.html`, `vite.config.ts` or CSP change.

## Design-source contradiction

`dashboard/COHORT_DISCOVERY.md` §3.3 says "Three columns on a wide screen; the assistant collapses
into a drawer below 1,200 px", and its Phase 1 paragraph ends "the assistant column is empty". The
owner removed the column on 2026-10-30 (review 2.5). The PR updates the Phase 1 paragraph's last
clause to:

> …and there is no assistant column: it was removed until chat ships (owner decision 2026-10-30,
> #98). The header holds History (↶/↷ and "Edit n"), Share, Compare and Feasibility statement; at
> 600 px and below they sit behind a ⋯ menu, and a sticky bar at the bottom shows the patient
> count.

The §3.3 wireframe and the "Three columns" sentence describe the target design including the
assistant (phase 3), so they stay. README's Discover paragraph ("Compare … and the Feasibility
statement are in the top bar") stays true. ARCHITECTURE, PLAN and COHORT_TOOL say nothing about
the Discover layout.

## Design

All changes are under `web/src/`, plus the one doc paragraph above.

| File | Change |
|---|---|
| `web/src/App.tsx` | header markup, History ↶/↷, Share panel, ⋯ menu, assistant removed, `SummaryBar` |
| `web/src/Answer.tsx` | export `TierPill` (extracted from `Cards`); Cohort ID line in Data notes; `tabIndex={-1}` on `#answer-h` |
| `web/src/Compare.tsx` | `versionLabel` reads `Edit n · name` (one spelling for a version) |
| `web/src/styles.css` | header, actions, ⋯ menu, centred two-column grid, summary bar, share link input |
| `web/src/app.test.tsx` | header, Share panel and summary bar tests |
| `web/src/answer.test.tsx` | Data notes cohort id test, `#answer-h` focus target |
| `web/src/styles.test.ts` | layout rules |
| `dashboard/COHORT_DISCOVERY.md` | §3.3 Phase 1 paragraph (above) |

### `Answer.tsx`

**`TierPill`** (exported). The two tier lines in `Cards` (`Answer.tsx:41-42`) move into it, and
`Cards` renders `<p className="sub"><TierPill perYear={perYear} /></p>` where it rendered the span.
The markup is identical to today's, so the #97 tier test still passes.

```tsx
/** The accrual tier as a pill: `tier tier-high|tier-moderate|tier-low`, with the tier's description as its title. */
export function TierPill({perYear}: {perYear: number}) {
  const t = tierFor(perYear);
  return <span className={`tier tier-${t.name.split(" ")[0].toLowerCase()}`} title={t.desc}>{t.name}</span>;
}
```

**Data notes tab** (`Answer.tsx:291`). After the notes list, one line with the counted result's
id:

```tsx
{tab === "Data notes" && <>
  <ul>{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
  <p className="hint">Cohort ID (for support): <code>{r.cohort_id}</code></p>
</>}
```

**Answer heading.** `<h2 id="answer-h" tabIndex={-1}>Answer</h2>`, so the summary bar's View link
can move focus to it. Item 3 renames the heading text; it keeps the id and `tabIndex`.

### `App.tsx`

#### State

- Delete the `link` state and `setLink(null)` in `setHist`. The Share panel always shows the link.
- `panel` becomes `"compare" | "feasibility" | "share" | null`.
- Add `const [menuOpen, setMenuOpen] = useState(false);` and
  `const moreRef = useRef<HTMLButtonElement>(null);`.
- `const go = (i: number) => { setHist({...histRef.current, current: i}); refresh(); };`. The
  History select's `onChange` and the ↶/↷ buttons call it.
- `togglePanel(p)` also calls `setMenuOpen(false)`.
- `share` replaces today's function. It opens the panel and tries the clipboard. Clicking Share
  while the panel is open closes it.

```ts
const share = async () => {
  setMenuOpen(false);
  if (panel === "share") { setPanel(null); return; }
  setPanel("share");
  setCopied(false);
  if (navigator.clipboard) {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true); } catch { /* the panel shows the link to copy */ }
  }
};
```

#### Header markup

The new header replaces `App.tsx:157-176`. Class names and ids are part of the contract, because
the CSS and tests use them.

```tsx
const single = hist.versions.length < 2;
const last = hist.versions.length - 1;
<header className="top"
  onKeyDown={(e) => { if (e.key === "Escape" && menuOpen) { setMenuOpen(false); moreRef.current?.focus(); } }}
  onBlur={(e) => {   // Tab out of the header closes the menu, so it never covers the focused control (WCAG 2.4.11)
    if (menuOpen && e.relatedTarget instanceof Node && !e.currentTarget.contains(e.relatedTarget)) setMenuOpen(false);
  }}>
  <h1>Discover</h1>
  <input aria-label="Cohort name" className="cohort-name" placeholder="Untitled cohort" value={name} maxLength={200}
    onChange={(e) => setName(e.target.value)} onBlur={commitName}
    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
  <div className="history">
    <button type="button" aria-label="Previous edit" title="Previous edit" disabled={hist.current === 0}
      onClick={() => go(hist.current - 1)}>↶</button>
    <button type="button" aria-label="Next edit" title="Next edit" disabled={hist.current === last}
      onClick={() => go(hist.current + 1)}>↷</button>
    <label>History{" "}
      <select aria-label="History" value={hist.current} onChange={(e) => go(Number(e.target.value))}>
        {hist.versions.map((v, i) => <option key={v.n} value={i}>Edit {v.n}</option>)}
      </select>
    </label>
  </div>
  <button type="button" ref={moreRef} className="more" aria-label="More actions" aria-expanded={menuOpen}
    aria-controls="header-actions" onClick={() => setMenuOpen(!menuOpen)}>⋯</button>
  <div id="header-actions" className={menuOpen ? "actions open" : "actions"}>
    <button type="button" className="btn-secondary" aria-expanded={panel === "share"} onClick={share}>Share</button>
    <button type="button" className="btn-secondary" aria-expanded={panel === "compare"} disabled={single}
      aria-describedby={single ? "compare-why" : undefined} onClick={() => togglePanel("compare")}>Compare</button>
    {single && <span id="compare-why" className="hint">Make a change to compare versions</span>}
    <button type="button" className="btn-primary" aria-expanded={panel === "feasibility"}
      disabled={panel !== "feasibility" && (!answer || stale)} onClick={() => togglePanel("feasibility")}>Feasibility statement</button>
  </div>
</header>
```

- No `<code>` and no `cohort_id` in the header.
- ↶, ↷ and ⋯ are plain buttons, which have the secondary look. They are not `.btn-icon`, because
  `.btn-icon` turns `--danger` red on hover and is for removal.
- The ⋯ menu is a disclosure (`aria-expanded` with `aria-controls`), not `role="menu"`. Its items
  are ordinary buttons reached with Tab, and the ⋯ button precedes `#header-actions` in the DOM so
  Tab from it enters the menu.
- The "Share link" button text becomes "Share". The input keeps `aria-label="Share link"`.

#### Panels

After the header, in this order: `share`, then `compare` and `feasibility` as today.

```tsx
{panel === "share" && (
  <SharePanel link={window.location.href} copied={copied} cohortId={answer && !stale ? answer.r.cohort_id : null}
    onClose={() => setPanel(null)} />
)}
```

`SharePanel` is exported, next to `FeasibilityPanel`. It is a panel under the header like the
other two, not an anchored popover: one placement works the same whether Share was opened from
the desktop header or from the ⋯ menu, and item 7 anchors all the panels together. The cohort id
shows only for a current answer, so it always belongs to the definition in the link.

```tsx
export function SharePanel({link, copied, cohortId, onClose}: {
  link: string; copied: boolean; cohortId: string | null; onClose: () => void;
}) {
  return (
    <section aria-label="Share" className="panel">
      <div className="row">
        <input readOnly aria-label="Share link" className="link" value={link} autoFocus onFocus={(e) => e.currentTarget.select()} />
        {copied && <span role="status">Link copied</span>}
        <button type="button" onClick={onClose}>Close</button>
      </div>
      {cohortId && <p className="hint">Cohort ID (for support): <code>{cohortId}</code></p>}
    </section>
  );
}
```

#### Columns and summary bar

Delete the `<aside aria-label="Assistant" …>` block (`App.tsx:192-195`). After `.cols`, as the
last child of `.app`:

```tsx
<SummaryBar answer={answer} options={options} />
```

`SummaryBar` is exported from `App.tsx`. Imports added: `Count` and `TierPill` from `./Answer.tsx`,
`accrualPerYear` from `./cohort.ts`, and `Options` is already imported. The window rule is the
same as `Cards`: the population years, else the data window.

```tsx
/** The patient count, tier and a jump to the answer: shown only at 600px and below (CSS). */
export function SummaryBar({answer, options}: {answer: Counted | null; options: Options | null}) {
  if (!answer) return null;
  const {d, r} = answer;
  const perYear = accrualPerYear(r.patients, d.population.years ?? options?.years ?? null);
  const view = (e: React.MouseEvent) => {
    e.preventDefault();   // a #answer-h fragment would replace the share hash in the address bar
    const h = document.getElementById("answer-h");
    h?.scrollIntoView();
    h?.focus();
  };
  return (
    <div className="summary-bar" role="region" aria-label="Cohort summary">
      <span><span className={r.patients == null ? "summary-count hatched" : "summary-count"}>
        <Count n={r.patients} minCell={r.min_cell} /></span> patients</span>
      {perYear != null && <TierPill perYear={perYear} />}
      <a href="#answer-h" onClick={view}>View</a>
    </div>
  );
}
```

The View link must not change the fragment. The address bar holds the share hash (`#d=…`),
which Share copies and `readShareHash` reads on load.

### `Compare.tsx`

`const versionLabel = (v: Version) => \`Edit ${v.n} · ${v.definition.name || "Untitled"}\`;`.
The header now calls a version "Edit n", so Compare's checkboxes and column heads use the same
words. `compare.test.tsx` builds its column labels itself, so no test changes.

### `styles.css`

Replace the `.top` rules, the `.cols`/`.assistant` rules and the media queries at
`styles.css:51-62` with the following. Add the summary bar rules, and add `.summary-count.hatched`
to the `td.hatched` rule (its 35% stripe keeps the muted "<5" readable). No raw hex colours.

```css
.app { max-width: 1280px; margin-inline: auto; }
.top { position: relative; display: flex; flex-wrap: wrap; align-items: center; gap: var(--s3); padding: var(--s3) var(--s4); border-bottom: 1px solid var(--line); background: var(--surface); }
.top h1 { margin: 0; }
.top .cohort-name { min-width: 16rem; font-size: var(--fs-xl); line-height: var(--lh-xl); font-weight: 600; background: transparent; border-color: transparent; }
.top .cohort-name:hover { border-color: var(--line); }
.history, .actions { display: flex; align-items: center; gap: var(--s2); }
.actions { margin-left: auto; }
.actions .hint { margin: 0; }
.more { display: none; }
.panel .link { flex: 1; min-width: 0; max-width: 40rem; }

.cols { display: grid; grid-template-columns: minmax(18rem, 22rem) 1fr; gap: var(--s6); padding: var(--s4); align-items: start; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.cols > * { min-width: 0; }

.summary-bar { display: none; }
@media (max-width: 600px) {
  .top .cohort-name { flex: 1 1 0; min-width: 0; }
  .more { display: inline-flex; align-items: center; justify-content: center; }
  .history { order: 1; flex-basis: 100%; }
  .actions { display: none; }
  .actions.open {
    display: flex; flex-direction: column; align-items: stretch; position: absolute; top: 100%; right: var(--s4); z-index: 20;
    margin: 0; padding: var(--s2); background: var(--bg); border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 8px 24px rgb(0 0 0 / .12);
  }
  .summary-bar {
    display: flex; align-items: center; gap: var(--s3); position: sticky; bottom: 0; z-index: 10;
    padding: var(--s2) var(--s4); background: var(--surface); border-top: 1px solid var(--line);
  }
  .summary-bar a { margin-left: auto; color: var(--accent); }
}
.summary-count { font-weight: 600; font-variant-numeric: tabular-nums; padding: 0 var(--s1); border-radius: 4px; }
```

How the ≤600px header lays out. The DOM order is h1, name, `.history`, ⋯, `.actions`. ⋯ comes before the menu it opens so that Tab
from ⋯ lands on Share (WCAG 2.4.3). Row 1 is
"Discover", the name (it takes the remaining width and truncates) and ⋯. `.history` has
`order: 1` and `flex-basis: 100%`, so it wraps to row 2 on its own. `.actions` is hidden, or when
open it is absolutely positioned under the header and takes no row. So the header is at most two
rows. The compare reason hint is inside `.actions`, so it shows in the open menu.

The 1280px cap is on `.app`, so the header and panels are centred with the grid. The summary bar
is the last child of `.app`, and `position: sticky; bottom: 0` keeps it at the viewport bottom
while `.app` is on screen. No ancestor sets `overflow`, which would break `sticky`.

## Acceptance criteria

- [ ] (a) No hash is visible in the header at any width: the header has no `<code>` and the
      `<header className="top">…</header>` block in `App.tsx` does not mention `cohort_id`
      (app tests 1 and 3). The id shows as "Cohort ID (for support)" in the Share panel (app test
      4) and the Data notes tab (answer test).
- [ ] (b) Exactly one `btn-primary` in the header, on Feasibility statement (app test 1).
- [ ] (c) There is no Assistant column: no `aria-label="Assistant"` and no "Coming later" in the
      page. `.cols` has two tracks and no `.assistant` rule exists, so at 1440px the answer column
      runs to the right edge of the 1280px content (app test 1, styles test 1; screenshot by the
      orchestrator).
- [ ] (d) At 390px the header is at most two rows, and the summary bar with the patient count (or
      "<5") stays at the bottom while scrolling. The ≤600px CSS hides `.actions`, shows `.more`,
      sends `.history` to its own row and makes `.summary-bar` sticky at `bottom: 0` (styles test
      2; screenshot by the orchestrator).
- [ ] (e) The summary bar renders "<5" inside `summary-count hatched` for a null count, never 0,
      and shows no tier pill (app test 5).
- [ ] With one version, Compare is disabled, has `aria-describedby="compare-why"` and the visible
      text "Make a change to compare versions", and ↶ and ↷ are disabled. With two versions and
      `current` on the last, Compare is enabled with no reason text, ↶ is enabled and ↷ is disabled
      (app tests 1 and 2).
- [ ] The History select is labelled "History" and its options read "Edit n" (app tests 1-2).
- [ ] The View link is `href="#answer-h"`, and its handler calls `preventDefault` so the share hash
      stays in the address bar. `#answer-h` has `tabindex="-1"` (app test 5, answer test).
- [ ] `COHORT_DISCOVERY.md` §3.3 Phase 1 records that the assistant column was removed.
- [ ] `bun run typecheck` and `bun test` pass. The existing tests pass, including the #97 tier
      test after the `TierPill` extraction.

## Test plan

```bash
cd web && bun install --frozen-lockfile && bun run typecheck && bun test
```

All tests use `renderToStaticMarkup` (no DOM library; none may be added) and synthetic
`CountResult`s like those already in `answer.test.tsx`. `App` renders statically under bun:
`useEffect` doesn't run, so a transport whose methods return `new Promise(() => {})` is enough, and
`answer` is null.

**`app.test.tsx`** (existing FeasibilityPanel tests stay):

1. *Header with one version.* `renderToStaticMarkup(<App transport={never} />)`. Slice the HTML
   from `<header` to `</header>` and check:
   - exactly one match of `btn-primary`, and it is on the button whose text is
     "Feasibility statement";
   - no `<code`;
   - `aria-label="History"`, `>Edit 1</option>`, and `aria-label="Previous edit"` and
     `aria-label="Next edit"` both `disabled`;
   - Compare has `disabled` and `aria-describedby="compare-why"`, and the text
     "Make a change to compare versions" is present;
   - `aria-label="More actions"`, `aria-expanded="false"` and `aria-controls="header-actions"`, and the ⋯ button
     comes before `id="header-actions"` in the header HTML (Tab from ⋯ enters the open menu).

   In the full HTML: no `aria-label="Assistant"` and no "Coming later".
2. *Header with two versions.* Before rendering, set
   `globalThis.localStorage = {getItem: () => JSON.stringify({versions: [{n: 1, definition: EMPTY}, {n: 2, definition: {...EMPTY, name: "b"}}], current: 1}), setItem: () => {}}`
   (cast through `unknown`). Delete it in a `finally`. `loadHistory` reads it. Check: options
   `Edit 1` and `Edit 2`; Previous edit enabled; Next edit disabled; Compare not disabled; no
   "Make a change to compare versions"; the name input's value is "b".
3. *Source pin.* `readFileSync(join(import.meta.dir, "App.tsx"), "utf8")`, sliced from
   `<header className="top">` to `</header>`, does not contain `cohort_id`.
4. *SharePanel.* With `link="http://x/#d=abc"`, `cohortId="v1-test"`: the HTML has
   `aria-label="Share link"`, `Cohort ID (for support)` and `<code>v1-test</code>`. With
   `cohortId={null}` there is no "Cohort ID". `copied` true shows "Link copied"; false does not.
5. *SummaryBar.* With `answer={d: EMPTY, r: result({patients: null}), p: null}` and options
   window `[2023, 2026]`: the HTML contains `class="summary-count hatched"`, `&lt;5` and no `>0<`;
   no `class="tier`; `href="#answer-h"` and `>View</a>`. With `patients: 400`: `400`, no
   `hatched`, and `class="tier tier-high"` (100 a year). With `answer={null}`: the empty string.
   The `result()` helper is a local copy of the one in `answer.test.tsx`.

**`answer.test.tsx`:** one new test. On the Data notes tab with `result()` (`cohort_id: "abc"`),
the HTML contains `Cohort ID (for support)` and `<code>abc</code>`. With any tab it contains
`id="answer-h" tabindex="-1"`.

**`styles.test.ts`:** two new tests.

1. *Two columns, centred.* `css` has no `.assistant`. `rule(".app")` contains
   `max-width: 1280px` and `margin-inline: auto`. `rule(".cols")` has a
   `grid-template-columns` value with exactly two top-level tracks (`minmax(18rem, 22rem) 1fr`).
2. *Mobile shell.* The body of `@media (max-width: 600px)` (match it with
   `/@media \(max-width: 600px\)\s*\{([\s\S]*?)\n\}/`) contains `.actions { display: none; }`, a
   `.more` rule with `display: inline-flex`, a `.history` rule with `flex-basis: 100%`, and a
   `.summary-bar` rule with `position: sticky` and `bottom: 0`. Outside it,
   `.summary-bar { display: none; }` is present. The `td.hatched` rule's selector includes
   `.summary-count.hatched`.

Not run, with reasons: `uv run pytest -q` is n/a (no Python or API model change). The dashboard
check is n/a (only `COHORT_DISCOVERY.md` prose under `dashboard/` changes). No test reads `$DATA`,
the de-id file, the PHI file or `$DATA/raw/`.

Visual check by the orchestrator on the dev server after merge, at 1440px light and dark and at
390px: the header row, no assistant column, the ⋯ menu open and closed, and the summary bar while
scrolling.

## Risks

- **Tight row 1 at 390px.** "Discover", the name and a 44px ⋯ (coarse pointer) leave about 200px
  for the name, so a long name truncates in its input. The full name is in the input and in the
  statement.
- **Focus after ↶/↷.** Stepping to the first or last edit disables the button that has focus, and
  the browser drops focus to the body. The History select next to it still works. A later change
  could move focus to the select.
- **Share now opens a panel.** One click still copies the link, as before, and also opens the
  panel. The link input is auto-focused and selected, so if the clipboard fails the link is ready
  to copy. Clicking Share again closes the panel.
- **The ⋯ menu doesn't close on an outside click.** It closes on ⋯, Escape or choosing an action.
  That is enough for three items; add click-outside handling if users report it.
- **Merge overlap.** Items 3, 4 and 7 also edit `Answer.tsx`, `styles.css` and `Compare.tsx`. This
  item's `Answer.tsx` edits are small (the `TierPill` extraction, Data notes, `tabIndex`), so
  conflicts should be mechanical. Item 3 must keep `id="answer-h" tabIndex={-1}` when it renames
  the heading.
- **CSS regex tests are brittle by design** (as in #97). A later item that renames `.actions`,
  `.more`, `.summary-bar` or the 600px breakpoint must update `styles.test.ts` in the same change.
