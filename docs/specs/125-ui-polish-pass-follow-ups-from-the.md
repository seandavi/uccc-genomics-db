# Spec #125: UI polish pass, follow-ups from the Discover redesign (#97–#104)

Issue #125 collects the open follow-ups from the #109, #113, #114, #117 and #123 reviews plus the
orchestrator's dev-site screenshot notes. This spec addresses every item: most are fixed, two were
already fixed on `origin/main` (only their spec text is left), and two nits are left as they are,
with the reason given. Line numbers are those on `origin/main` at e0c4ffb.

Everything is in `web/` and in Markdown. No patient data is involved; the examples below are the
synthetic ones the web tests already use.

| Item | Where | Decision (section below) |
|---|---|---|
| #109 code-r0-1 / ux-r0-3 / ux-r1-1 | `App.tsx:295` Escape only on `#header-actions` | Fix: Escape and Tab-out on `<header>` (§1) |
| #109 code-r0-3 | `app.test.tsx:51` loose `aria-expanded` check | Fix: pin the ⋯ button (§1) |
| #109 ux-r0-2 | Compare chosen from ⋯ drops focus to `<body>` | Fix: Compare focuses its first control (§2) |
| #109 ux-r0-4 | `SummaryBar` has no busy/stale state | Fix: dim + "Counting…"/"Out of date" (§3) |
| #109 ux-r0-5 | Summary link text "View" | Fix: "View answer" (§3) |
| #109 ux-r1-2 | History DOM order vs mobile visual order | **Leave it** (§1, reason) |
| #113 code-r0-2 | no test pins the mobile card grid | Fix: test, with the breakpoint change (§5) |
| #113 ux-r0-2 | "More in Data notes" leaves focus behind | Fix: focus the tab, as the arrow keys do (§4) |
| #113 ux-r0-3 | §3.3 wireframe shows the old funnel copy | Fix: new heading and step rows (§8) |
| #113 ux-r0-4 | `2fr 1fr 1fr` cramped at 801–960px | Fix: two-column cards up to 960px (§5); widening the wireframe card: skipped |
| #113 ux-r1-1 | footnote button is colour-only | Fix: underline (§5) |
| #113 ux-r1-2 | "− KRAS mutation + VUS" | Fix: tier suffix "(incl. VUS)" (§6) |
| #114 code-r0-1 | typeahead row `gap: 0` | Code already fixed (3380b9f); fix spec 101 + add a styles test (§7, §8) |
| #114 code-r0-2 | spec 101 acceptance (b) over-claims | Reword (b) (§8) |
| #114 ux-r0-1 | same-report switch hidden for one negated criterion | Code, test and COHORT_DISCOVERY already fixed (3380b9f); fix spec 101 snippet, acceptance and Risks (§8) |
| #114 ux-r0-2 | test name "no Or… for data" | Fix: rename (§7) |
| Screenshot: card header | mode select too wide, label wraps, dangling " · " | Fix (§7) |
| Screenshot: Remove ✕ | alone on a third row | Fix: into the header, top right (§7) |
| Screenshot: cohort name | truncated with free space | Fix: name input grows (§1) |
| Screenshot: header wraps | "Make a change to compare versions" inline | Fix: visually hidden description + tooltip (§1) |
| #117 code-r0-1 / ux-r0-1 | spec 104 rationale and Risks | Fix spec 104 text (§8) |
| #123 code-r0-1 | Escape test matches the header handler | Fix: slice the panel source (§2) |
| #123 code-r0-2 | focus restored to a trigger the close disables | Fix: restore after the commit, skip disabled (§2) |
| #123 code-r0-3 | "two or more edits" off by one | Fix: "two or more versions" (§2) |
| #123 ux-r0-1 | `.tabs` clips the focus ring | Fix: inset outline on tab buttons (§4) |
| #123 ux-r0-2 | pivot suggestion drops focus; waiting line silent | Fix: focus Rows, keep it mounted; `role="status"` (§4) |
| #123 ux-r0-3 | "Year" in suggestion labels | Fix: purpose line says "year of first report" (§4) |

## Goal

1. Escape closes the ⋯ menu from anywhere in the header (including with focus on ⋯), and the
   menu closes when Tab moves focus out of the header, so it never covers the focused control.
2. No panel open or close leaves focus on `<body>` or on a disabled button.
3. The mobile summary bar never shows a count at full strength once it is out of date.
4. At 1440px the header is one row, in both the empty (one version) and built states, and the
   cohort name uses the free space.
5. A criterion card's header is one row: mode pill · label … ✕. The label wraps inside its own box
   only when it is long. Text actions (Edit, + Or another, + Later report) sit on a row below,
   which is not rendered when a card has none.
6. The remaining copy, CSS and spec fixes in the table above.

## Non-goals

- **No data or output-path change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/src/`
  or `systemd/` changes. No schema, table, column, API model, route or operation changes, so
  `web/openapi.json` and `web/src/api.gen.ts` don't change (`bun run typecheck` checks it). Every
  number shown still comes from the same `CountResult`/`PivotResult` through the same `Count`
  component, so no small-cell rule changes and no new one is needed. The new summary-bar words
  ("Counting…", "Out of date") are fixed strings. **`research_id` and `report_id` stability is not
  affected.**
- No new dependency (React 19.3.1 and the existing `bun test` + `renderToStaticMarkup` setup; no
  DOM emulator).
- No click-outside handling for the ⋯ menu (unchanged from #98). Only Tab-out is added.
- No `popstate` handling and no de-duplication of versions on Back/Forward (#117 is a spec text
  fix only).
- #109 ux-r1-2 is left as it is (reason in §1). The optional "widen the patients card" in the
  §3.3 wireframe is skipped: the wireframe is an illustration and the bullets below it describe the
  cards.

## Design

Files changed: `web/src/App.tsx`, `web/src/Answer.tsx`, `web/src/Builder.tsx`,
`web/src/Compare.tsx`, `web/src/cohort.ts`, `web/src/styles.css`, their tests
(`app.test.tsx`, `answer.test.tsx`, `builder.test.tsx`, `compare.test.tsx`, `cohort.test.ts`,
`styles.test.ts`), `dashboard/COHORT_DISCOVERY.md` (wireframe only), and the earlier specs
`docs/specs/98-…`, `101-…`, `103-…`, `104-…` (text only, as the review items ask).

### §1 Header (`App.tsx`, `styles.css`)

**Escape and Tab-out on the header** (#109 code-r0-1, ux-r0-3, ux-r1-1). Remove the `onKeyDown`
from `<div id="header-actions">` and put both handlers on the header element:

```tsx
<header className="top"
  onKeyDown={(e) => { if (e.key === "Escape" && menuOpen) { setMenuOpen(false); moreRef.current?.focus(); } }}
  onBlur={(e) => {   // Tab out of the header closes the menu, so it never covers the focused control (WCAG 2.4.11)
    if (menuOpen && e.relatedTarget instanceof Node && !e.currentTarget.contains(e.relatedTarget)) setMenuOpen(false);
  }}>
```

- React's `onBlur` bubbles (it is `focusout`), so the header sees blur from ⋯ and from every menu
  item. Focus moving between ⋯, the name, History and the menu items stays inside the header and
  keeps the menu open.
- `relatedTarget` is `null` when focus goes nowhere (a click on empty page, or Safari's mouse click
  on a button, which doesn't focus it). The menu stays open then, so a mouse click on a menu item
  is never swallowed by a close on mousedown. That keeps #98's "no click-outside" behaviour.

**⋯ test** (#109 code-r0-3): in `app.test.tsx` `describe("header")` → "one version…", replace
`expect(h).toContain('aria-expanded="false"')` and `expect(h).toContain('aria-controls="header-actions"')`
with

```ts
expect(h).toMatch(/aria-label="More actions"[^>]*aria-expanded="false"[^>]*aria-controls="header-actions"/);
```

Keep the `aria-label="More actions"` check and the order check (`aria-controls` before
`id="header-actions"`).

**Compare's reason off the visible row** (screenshot after #120). The reason stays the button's
accessible description but is visually hidden, and is the button's tooltip:

```tsx
<button type="button" ref={compareRef} className="btn-secondary" aria-expanded={panel === "compare"} disabled={single}
  aria-describedby={single ? "compare-why" : undefined} title={single ? COMPARE_WHY : undefined}
  onClick={() => togglePanel("compare")}>Compare</button>
{single && <span id="compare-why" className="sr-only">{COMPARE_WHY}</span>}
```

with a module constant above `App`: `const COMPARE_WHY = "Make a change to compare versions";`.
Delete the now-unused `.actions .hint { margin: 0; }` rule from `styles.css`.

**Cohort name grows** (screenshot after #115/#116). Base rule:

```css
.top .cohort-name { flex: 1 1 16rem; min-width: 16rem; text-overflow: ellipsis; font-size: var(--fs-xl); line-height: var(--lh-xl); font-weight: 600; background: transparent; border-color: transparent; }
```

The 600px rule `.top .cohort-name { flex: 1 1 0; min-width: 0; }` stays and still wins on phones.
With the name growing, `.actions { margin-left: auto; }` has no effect on desktop; leave it (it
still right-aligns the actions when the name has hit its row's end on a narrow window).

**#109 ux-r1-2: left as it is.** Moving `.history` after `#header-actions` in the DOM and using
`order` on desktop would make the desktop Tab order name → Share/Compare/Feasibility → History
while History is drawn before them, i.e. the same 2.4.3 mismatch moved to the primary layout. At
600px and below the mismatch is one stop (History on row 2 before ⋯ on row 1), and ⋯ is the next
stop. Spec 98's Risks are not changed for this; this paragraph is the record.

### §2 Panels and focus (`App.tsx`, `Compare.tsx`)

**Compare takes focus when it opens** (#109 ux-r0-2). Feasibility already focuses its heading on
mount (#103) and Share auto-focuses its link input. In `Compare.tsx`, the first version checkbox
gets `autoFocus={i === 0}` (the `versions.map` callback gains its index `i`), and in the
one-version branch the Close button gets `autoFocus`. Opening Compare from the mobile ⋯ menu then
lands focus in the panel instead of on `<body>`; on desktop it moves from the trigger into the
panel, as Share does.

**Restore focus after the commit; skip a disabled trigger** (#123 code-r0-2). `focusTrigger` gains
a fallback and a disabled check:

```ts
/** Focus back on the button that opened a panel; else on ⋯ (the trigger sits in the closed mobile menu); else on
 *  fallback (the answer heading). An element is skipped when hidden (offsetParent null) or disabled. */
export function focusTrigger(trigger: HTMLElement | null, more: HTMLElement | null, fallback: HTMLElement | null): void {
  const usable = (el: HTMLElement | null): el is HTMLElement =>
    el !== null && el.offsetParent !== null && !(el as HTMLButtonElement).disabled;
  (usable(trigger) ? trigger : usable(more) ? more : fallback)?.focus();
}
```

`closePanel` closes first and restores focus in the next frame, after React has committed the
close (so the Feasibility trigger's `disabled` reflects `!answer || stale` by then):

```ts
const closePanel = () => {
  const trigger = panel ? {share: shareRef, compare: compareRef, feasibility: feasibilityRef}[panel].current : null;
  setPanel(null);
  requestAnimationFrame(() => focusTrigger(trigger, moreRef.current, document.getElementById("answer-h")));   // after the commit: a trigger the close disabled is skipped
};
```

`#answer-h` is always mounted with `tabIndex={-1}` (it is `jumpToAnswer`'s target). This is the
same `requestAnimationFrame` pattern `applyExample` uses.

**Compare copy** (#123 code-r0-3). `Compare.tsx` one-version text becomes "Compare needs two or
more versions. Make a change to the cohort, then compare the versions here."

**Escape test** (#123 code-r0-1). In `app.test.tsx` `describe("panel source")`, replace
`expect(src).toContain('e.key === "Escape"')` with a check on the panel's own source:

```ts
const panelSrc = src.slice(src.indexOf("export function FeasibilityPanel"), src.indexOf("export function", src.indexOf("export function FeasibilityPanel") + 1));
expect(panelSrc).toContain('if (e.key === "Escape") onClose();');
```

### §3 Summary bar (`App.tsx`)

#109 ux-r0-4 and ux-r0-5:

```tsx
/** The patient count, tier and a jump to the answer: shown only at 600px and below (CSS). While a recount runs, or
 *  when the count is for an earlier version (the recount failed), they are dimmed and a word says so. */
export function SummaryBar({answer, options, busy = false, stale = false}: {
  answer: Counted | null; options: Options | null; busy?: boolean; stale?: boolean;
}) {
  …unchanged up to the return…
  const dim = busy || stale ? "dim" : undefined;
  return (
    <div className="summary-bar" role="region" aria-label="Cohort summary">
      <span className={dim}><span className={…unchanged…}><Count … /></span> patients</span>
      {perYear != null && <span className={dim}><TierPill perYear={perYear} /></span>}
      {(busy || stale) && <span className="hint">{busy ? "Counting…" : "Out of date"}</span>}
      <a href="#answer-h" onClick={view}>View answer</a>
    </div>
  );
}
```

`App` renders `<SummaryBar answer={answer} options={options} busy={busy} stale={stale} />` (`stale`
is the existing `!!answer && answer.d !== current`). `.dim` already exists (`opacity: .55`).

### §4 Answer column (`Answer.tsx`, `styles.css`)

**Focus follows "More in Data notes"** (#113 ux-r0-2). A module function shared with the arrow keys:

```ts
/** Selects tab t and moves focus to its tab button, which is always rendered with the answer. */
function selectTab(t: Tab, onTab: (t: Tab) => void): void {
  onTab(t);
  document.getElementById(`tab-${TABS.indexOf(t)}`)?.focus();
}
```

`onKey` ends with `e.preventDefault(); selectTab(TABS[next], onTab);` (replacing its `onTab` and
`focus` lines), and `DataFootnote`'s button calls `onClick={() => selectTab("Data notes", onTab)}`.
Focusing the tab button scrolls it into view.

**Tab focus ring** (#123 ux-r0-1): add `.tabs button:focus-visible { outline-offset: -2px; }`
after the `.tabs button` rules. The ring draws inside the button, so `.tabs`' `overflow-x: auto`
no longer clips it and the tab row's layout is unchanged.

**Pivot suggestions** (#123 ux-r0-2, ux-r0-3). In `PivotTab`:

- `const rowsRef = useRef<HTMLSelectElement>(null);`. The `select` helper takes an optional
  fourth argument `ref?: React.RefObject<HTMLSelectElement | null>` and puts it on the
  `<select>`; the Rows call passes `rowsRef`.
- Each suggestion button: `onClick={() => { choose(s.rows, s.cols); rowsRef.current?.focus(); }}`.
- The waiting line becomes `<p role="status">The table appears once it is counted.</p>`.
- The focused Rows select must survive the apply round trip. Today `Answer` renders
  `<PivotTab key={JSON.stringify(definition.pivot)} …>`, so the new `d.pivot` remounts PivotTab and
  drops focus again. Remove that `key` and reset the local selects from the definition instead:

  ```ts
  useEffect(() => { setRows(d.pivot?.rows ?? ""); setCols(d.pivot?.cols ?? ""); }, [d.pivot?.rows, d.pivot?.cols]);   // replaces a key remount, which dropped focus
  ```

  The behaviour is the same as the remount: History navigation and a cleared pivot reset both
  selects; a half-chosen pair (one select set, `d.pivot` unchanged) keeps its local value.
  `Answer.tsx` imports `useEffect` and `useRef` from `react`.
- The purpose line reads "Count patients for every combination of two characteristics, such as
  tumor type by year of first report." The suggestion labels ("Tumor type × Year", …) stay short.

### §5 Answer CSS (`styles.css`)

**Cards** (#113 ux-r0-4, code-r0-2). Replace

```css
@media (max-width: 600px) { .cards { grid-template-columns: 1fr 1fr; } }   /* after .cards: same specificity, later wins */
```

with

```css
@media (max-width: 960px) { .cards { grid-template-columns: 1fr 1fr; } .card.hero { grid-column: 1 / -1; } }   /* after .cards: same specificity, later wins */
```

and delete `.card.hero { grid-column: 1 / -1; }` from the 600px shell block. From 801px to 960px
the answer column is about 385–545px wide; there the hero takes the first row and Accrual and Share
share the second. Below 800px the columns stack, and the same two-row card layout applies. Above
960px the `2fr 1fr 1fr` row is unchanged.

**Footnote link** (#113 ux-r1-1):
`.footnote .btn-tertiary { min-height: 0; padding: 0; text-decoration: underline; text-underline-offset: 2px; }`.

### §6 Tier suffix (`cohort.ts`)

#113 ux-r1-2. In `tierSuffix`, the default-tiers-plus-extras branch returns
`` ` (incl. ${extras.join(", ")})` `` instead of `` ` + ${extras.join(" + ")}` ``, where `extras`
is the existing `tier.filter((t) => !DEFAULT_TIERS.includes(t)).map((t) => TIER_NAMES[t])`.
Examples: `ALK fusion (incl. VUS)`, `KRAS mutation (incl. VUS, unclassified)`. The other two
branches are unchanged (`""`, and `(VUS only)`-style). Every label built on `criterionBody`
changes with it: card labels, funnel steps ("− KRAS mutation (incl. VUS)"), Compare's Definition
row and the Feasibility statement text.

### §7 Criterion card (`Builder.tsx`, `styles.css`)

Screenshot notes after #115/#116 and #114 ux-r0-2.

`CriterionCard` returns:

```tsx
<article className={`criterion mode-${c.mode}`} aria-label={capitalise(criterionLabel(c))}>
  <header>
    <select className="mode" …unchanged…>…</select>
    <span className="sep" aria-hidden="true">·</span>
    <span className="clabel">{label}</span>
    <button type="button" className="btn-icon remove" aria-label={`Remove ${label}`} title="Remove this criterion"
      onClick={() => onOp({op: "remove_criterion", id})}>✕</button>
  </header>
  …any_of members and SequenceMembers unchanged…
  {actions.length > 0 && <div className="row card-actions">{actions}</div>}
  …editor and typeaheads unchanged…
</article>
```

CSS:

```css
.criterion header { display: flex; align-items: center; gap: var(--s1); margin-bottom: .3rem; }   /* no wrap: a long label wraps inside .clabel */
.criterion header .clabel { flex: 1; min-width: 0; }
.criterion header .remove { flex: none; }
.criterion .mode { flex: none; field-sizing: content; …existing declarations… }
.criterion .sep { color: var(--muted); }
```

- `flex-wrap: wrap` is removed from `.criterion header`, so the label never drops to its own line
  and the separator always sits between two visible items (the select and the label).
- `field-sizing: content` sizes the select to the selected option where supported (Chromium
  123+); elsewhere the select keeps its native width (the widest option), which the no-wrap header
  absorbs (see Risks).
- `.card-actions .sep { color: var(--muted); }` becomes `.criterion .sep` (above) and covers both
  separators; `.card-actions .remove { margin-left: auto; }` is deleted.
- Rename the builder test "a per-patient data criterion has no Edit; no Or… for data" to "a
  per-patient data criterion has no Edit; no + Or another for data".

### §8 Documentation

- **`dashboard/COHORT_DISCOVERY.md` §3.3 wireframe** (#113 ux-r0-3): only the centre segment of
  lines 317–321 changes (each segment stays 52 characters wide; the left and right segments are
  untouched):

  ```
    HOW EACH CRITERION NARROWS THE COHORT             
    NSCLC 2023+                  120 ██████████████   
    + KRAS G12C                    8 █                
    − STK11 or KEAP1 alteration    6 █                
    + PD-L1 TPS ≥ 50              <5 ▒                
  ```

- **`docs/specs/98-ui-layout-shell-header-history-no.md`** (#109 code-r0-1): in the header
  snippet, move the Escape `onKeyDown` from `<div id="header-actions">` to `<header className="top">`
  and add the `onBlur` from §1; in Non-goals, after "It closes on ⋯, on Escape and when an action
  in it is chosen." add "Since #125 it also closes when Tab moves focus out of the header."
- **`docs/specs/101-ui-builder-controls-and-criterion-cards.md`** (#114):
  - toggle snippet: `const showSameReport = d.scope === "report" || d.criteria.length >= 2 || d.criteria.some((c) => c.mode !== "include");`
  - CSS snippet: `.typeahead li { justify-content: flex-start; gap: var(--s1); }`, and the bullet
    below it reads "In the existing `.typeahead li` rule, drop `justify-content: space-between`
    and use a `var(--s1)` gap: the row is a flex container, so the spaces around the ' · '
    separator collapse and the gap provides them."
  - acceptance (b): replace "The row markup is badge, " · ", text." with "The row markup (badge,
    ' · ', text) is checked by the orchestrator's screenshot 02, not by a test; the row's gap is
    pinned in `styles.test.ts`."
  - same-report acceptance: "absent with zero criteria, or with one include criterion, at patient
    scope; present after the last card with two criteria or with any exclude or tested-negative
    criterion, and present and checked at report scope even with none."
  - Risks, "Hidden toggle state": "The same-report toggle hides at one include criterion. …" (the
    rest unchanged).
- **`docs/specs/103-ui-panels-and-tabs-feasibility-compare.md`** (#123): "Compare needs two or
  more edits" → "Compare needs two or more versions" in the snippet and the test plan; add to
  Risks: "**Focus after closing a panel.** `closePanel` restores focus after the close commits,
  skipping a trigger that is hidden or now disabled (the Feasibility button when the cohort was
  edited while the panel was open): ⋯ next, then the answer heading (#125)."
- **`docs/specs/104-ui-share-link-pasted-into-an-open-tab-is.md`** (#117): after the paragraph
  under "Why the app's own writes need a guard at all", add: "Back/Forward can also reach an entry
  holding another version's hash. Pasting link B into a tab showing A creates a new history entry
  whose state `setHist` replaces, but the previous entry still holds A's hash. Back then fires
  `hashchange` with A's hash, which is not the current version, so `applyShareHash` adds A as a new
  version; Forward adds B again." Add to Risks: "**Back/Forward across a pasted link** re-applies
  the other entry's cohort as a new version (no popstate handling, by design); ↶/↷ is the in-app
  undo. A later change could select an existing equal version instead of pushing."

## Acceptance criteria

- [ ] (1) `App.tsx`: the Escape handler and the Tab-out `onBlur` are on `<header className="top">`;
      `<div id="header-actions">` has no `onKeyDown` (source test).
- [ ] (2) The header test pins the ⋯ button with
      `/aria-label="More actions"[^>]*aria-expanded="false"[^>]*aria-controls="header-actions"/`.
- [ ] (3) One version: the header has `<span id="compare-why" class="sr-only">Make a change to
      compare versions</span>`, the Compare button has `title="Make a change to compare versions"`
      and `aria-describedby="compare-why"`, and the header has no `class="hint"`. Two versions:
      none of these (app test). `styles.css` has no `.actions .hint` rule.
- [ ] (4) `rule(".top .cohort-name")` contains `flex: 1 1 16rem` and `min-width: 16rem` (styles test).
- [ ] (5) `Compare` with two versions renders `autofocus=""` on the first checkbox only; with one
      version, on Close; its text is "Compare needs two or more versions." (compare tests).
- [ ] (6) `focusTrigger`: a visible enabled trigger takes focus; a disabled or hidden trigger sends
      focus to a visible ⋯; with ⋯ hidden too, to the fallback; all null is a no-op (unit tests with
      fake elements `{offsetParent, disabled, focus}`). `closePanel` calls `focusTrigger` inside
      `requestAnimationFrame` after `setPanel(null)` with `document.getElementById("answer-h")` as
      the fallback (source test).
- [ ] (7) The Feasibility Escape test checks `if (e.key === "Escape") onClose();` inside the
      `FeasibilityPanel` source only.
- [ ] (8) `SummaryBar`: link text `>View answer</a>`; with `busy` it contains "Counting…" and
      `class="dim"`; with `stale` (not busy) "Out of date" and `class="dim"`; with neither, no
      `dim`, no "Counting…", no "Out of date". `App` passes `busy` and `stale` (app tests).
- [ ] (9) `DataFootnote` and `onKey` both go through `selectTab` (source test on `Answer.tsx`).
- [ ] (10) `rule(".tabs button:focus-visible")` contains `outline-offset: -2px` (styles test).
- [ ] (11) Pivot: the waiting line is `<p role="status">The table appears once it is counted.</p>`;
      the purpose line ends "such as tumor type by year of first report."; `Answer.tsx` has no
      `key={JSON.stringify(definition.pivot)}`, and the suggestion `onClick` contains
      `rowsRef.current?.focus()` (answer tests, source test for the last two).
- [ ] (12) `styles.css` has `@media (max-width: 960px) { .cards { grid-template-columns: 1fr 1fr; } .card.hero { grid-column: 1 / -1; } }`
      after the base `.cards { display: grid` rule (`indexOf` comparison), and the 600px shell block
      no longer holds `.card.hero` (styles test; the mobile-shell test drops its `.card.hero` line).
- [ ] (13) `rule(".footnote .btn-tertiary")` contains `text-decoration: underline` (styles test).
- [ ] (14) `criterionLabel` of ALK fusion with tiers likely pathogenic, pathogenic and VUS is
      "ALK fusion (incl. VUS)" (cohort test). A funnel with an exclude KRAS mutation criterion with
      `tier: ["likely_pathogenic", "pathogenic", "vus"]` contains "− KRAS mutation (incl. VUS)" and
      no "+ VUS" (answer test).
- [ ] (15) Criterion card: the header (from `<header>` to `</header>` of the card) contains, in
      order, the mode select, `<span class="sep" aria-hidden="true">·</span>`,
      `<span class="clabel">…</span>` and `class="btn-icon remove"`; an alteration card has a
      `card-actions` row; a sequence card has none (builder tests). `rule(".criterion header")`
      has no `flex-wrap`, `rule(".criterion header .clabel")` contains `min-width: 0`, and
      `rule(".criterion .mode")` contains `field-sizing: content` (styles tests). The existing
      Remove test still passes.
- [ ] (16) `rule(".typeahead li")` contains `gap: var(--s1)` (styles test). The builder test is
      renamed "a per-patient data criterion has no Edit; no + Or another for data".
- [ ] (17) The doc edits in §8 are made: COHORT_DISCOVERY.md wireframe (no "FUNNEL", no "∧ " step
      rows, every changed line still the same width as its neighbours), and specs 98, 101, 103 and
      104.
- [ ] (18) `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes.
      `uv run pytest -q` and the dashboard check are n/a (`web/` and Markdown only, no API model
      change); report them as n/a.
- [ ] (19) Orchestrator, on the dev site after merge: at 1440px light, the header is one row in the
      empty and built states and the name shows in full when there is room; an exclude card reads
      `EXCLUDE · KEAP1 or STK11 alteration … ✕` on one row with ✕ top right; the typeahead row
      reads "Gene alteration · KRAS"; at 390px the summary bar dims while counting; at ~880px the
      cards are hero on top, two below.

## Test plan

All tests are `bun test` files in `web/src/`, static renders with `renderToStaticMarkup` or source
checks with `readFileSync`, as the existing ones are. No network, no `$DATA`, no patient data.

- `app.test.tsx`: criteria (1), (2), (3), (6), (7), (8). The `focusTrigger` fake becomes
  `fake(offsetParent, disabled = false)`; existing calls pass `null` as the third argument. The
  source test for (1) slices `src` from `'<header className="top"'` to `"<h1>Discover</h1>"` and
  from `'<div id="header-actions"'` to the next `"<button"`.
- `compare.test.tsx`: (5), and the existing one-version test's matcher changes to "Compare needs
  two or more versions".
- `answer.test.tsx`: (9), (11), (14 funnel). Add `readFileSync`/`join` imports for the source tests.
- `builder.test.tsx`: (15), (16 rename).
- `cohort.test.ts`: (14 label), replacing the "ALK fusion + VUS" expectation.
- `styles.test.ts`: (4), (10), (12), (13), (15 CSS), (16 gap).

## Risks

- **`field-sizing` support.** Firefox, and Safari versions without it, keep the native select width
  (the widest option, "Tested negative" on alteration cards), so the pill can be wider than its
  text there. The header no longer wraps, so this costs label width only. The orchestrator's
  screenshot is Chromium.
- **Tab-out closes the menu; a click outside does not.** A mouse user who opens ⋯ and clicks
  elsewhere still has to press ⋯ or Escape, as in #98.
- **The disabled Compare's tooltip.** Browsers show `title` on a disabled button inconsistently,
  and a disabled button is not focusable, so a sighted keyboard user doesn't see the reason. A
  screen reader reads it through `aria-describedby`; the Compare panel, once open, still explains
  itself. Accepted to keep the header one row, as the screenshot note asks.
- **Focus restore in the next frame.** Between the close and the frame, focus is briefly on
  `<body>`; screen readers announce the restored element. Same pattern as `applyExample`.
- **The PivotTab `key` removal** changes how local select state resets, from a remount to an
  effect. The effect's dependencies are the two pivot axes, so a change of definition that keeps
  the pivot keeps a half-chosen pair, as the keyed version did.
- **Copied grant text changes** where a criterion includes VUS or unclassified tiers ("(incl.
  VUS)" instead of "+ VUS"). It contains no number.
- **Cards between 601px and 800px** now use two rows (hero, then two cards) at full width, where
  three columns fitted. That is a little taller, and consistent with phones.
