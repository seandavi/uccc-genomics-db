# Spec #97: UI design tokens and base controls

Issue #97 is item 1 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`, §1
problems, §2 design direction, §3 item 1). It replaces the colour variables in
`web/src/styles.css` with the §2 token set, adds the type-scale and spacing tokens, and fixes the
base controls. Items 2-7 (#98-#104) build on these tokens; this item changes no layout and no
markup.

## Goal

1. `:root` holds the §2 colour tokens for light and dark, plus the type-scale and spacing tokens.
   Every other rule uses `var(--…)`; no raw hex colour appears outside the two `:root` blocks.
2. The base size is 16px. Every `font-size` in `styles.css` uses a type-scale token.
3. `textarea` is in the base control rule, so the feasibility statement is in the page's
   proportional font, not the browser's default monospace (review 2.8, screenshot 04).
4. The button classes `.btn-primary`, `.btn-secondary`, `.btn-tertiary` and `.btn-icon` exist.
   A plain `button` keeps the secondary look.
5. Controls are at least 36px tall, and at least 44px on coarse pointers. Chip "×" buttons are at
   least 24×24px (44×44 on coarse pointers). `.sr-only` uses the standard clip pattern (review
   3.1, 3.2).
6. Suppressed hatching uses `--suppressed-bg` and `--suppressed-stripe`. In dark mode the stripes
   are muted grey, not near-white (review 2.1, screenshot 08).
7. The accrual tier is a pill: a tinted `-bg` background with coloured text. High is green,
   Moderate is amber and Low / pilot is orange. None of them is the accent blue or the error red
   (review 2.2).

## Non-goals

- **No markup change.** `Answer.tsx:41-42` already renders
  `<span class="tier tier-high|tier-moderate|tier-low" title=…>`. The pill is CSS on those
  classes, so `Answer.tsx` doesn't change. The issue lists `Answer.tsx:41-42` as a file that may
  change; it doesn't need to. A new test in `answer.test.tsx` pins the three class names the CSS
  depends on.
- No layout, header, card-size, chart, tab, typeahead or builder change. Those are items 2-7. The
  `.btn-*` classes are defined here and applied to markup there.
- No spacing refactor of existing rules. The spacing tokens are defined and used by the rules this
  item writes: the base controls, the buttons, the tier pill and `.error`. Other paddings and
  margins keep their current `rem` values until the items that restyle them.
- No shadows, card radii, tab underline or floating-layer styling (§2 "Shape and elevation" beyond
  the 6px control radius). Those belong to the items that touch those elements.
- No web font, CDN, new dependency, or change to `vite.config.ts`, `index.html`, the CSP, the
  definition and operations model, the share link or `transport.ts`.
- **No data or output-path change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/` or
  `systemd/` changes. No schema, table or column changes, and no new output path, so no new
  small-cell rule is needed. Suppressed counts still render as the `Count` component's "<5" text
  and stay hatched; only the hatch colours change. **`research_id` and `report_id` are not
  touched.**
- No design-source contradiction. `COHORT_DISCOVERY.md` §3.3 ("years under 5 are drawn as a
  hatched '<5' bar … partial years are shaded") still holds. ARCHITECTURE, README, PLAN and
  COHORT_TOOL say nothing about Discover's colours. Spec #37 described hatching as stripes "over
  the bar colour"; that spec is a historical record, so it isn't edited. The hatch now sits over
  `--suppressed-bg`.

## Design

Two files change and one is added, all under `web/src/`:

| File | Change |
|---|---|
| `web/src/styles.css` | tokens, base controls, buttons, `.sr-only`, hatch, tier pill, coarse-pointer rule |
| `web/src/styles.test.ts` | **new**: policy-style checks on `styles.css` (pattern of `policy.test.ts`) |
| `web/src/answer.test.tsx` | one new test pinning the tier class names |

### `styles.css`: the `:root` blocks

Replace lines 1-15 with the following. The colours are the review's §2 values (Primer palette).
`--panel`, `--err-bg` and `--err-fg` are removed. `--surface` replaces `--panel`. `.error` is
derived from `--danger` with `color-mix` (below), so the token set stays exactly §2's.

```css
:root {
  color-scheme: light dark;
  --bg: #ffffff; --surface: #f6f8fa; --surface-2: #eef1f4; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0;
  --accent: #0969da; --accent-fg: #ffffff; --bar: #54aeff; --bar-partial: #b6e3ff;
  --high: #1a7f37; --high-bg: #dafbe1; --moderate: #9a6700; --moderate-bg: #fff8c5; --low: #bc4c00; --low-bg: #fff1e5;
  --danger: #d1242f; --suppressed-bg: #eef1f4; --suppressed-stripe: #8c959f;
  --fs-xs: 12px; --lh-xs: 16px; --fs-sm: 13px; --lh-sm: 18px; --fs-md: 16px; --lh-md: 24px;
  --fs-lg: 18px; --lh-lg: 26px; --fs-xl: 22px; --lh-xl: 28px; --fs-2xl: 28px; --lh-2xl: 32px;
  --fs-hero: 44px; --lh-hero: 48px;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: var(--fs-md); line-height: var(--lh-md);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --surface: #161b22; --surface-2: #21262d; --fg: #e6edf3; --muted: #9198a1; --line: #3d444d;
    --accent: #4493f8; --accent-fg: #0d1117; --bar: #388bfd; --bar-partial: #1f3a5f;
    --high: #3fb950; --high-bg: #12261e; --moderate: #d29922; --moderate-bg: #272115; --low: #db6d28; --low-bg: #2a1b14;
    --danger: #f85149; --suppressed-bg: #21262d; --suppressed-stripe: #656c76;
  }
}
```

Contrast for the text pairs, computed with the WCAG relative-luminance formula while writing
this spec (light / dark). `styles.test.ts` recomputes them; all must be ≥ 4.5:1.

| Pair (text / background) | Light | Dark |
|---|---|---|
| `--fg` / `--bg` | 15.8 | 16.0 |
| `--fg` / `--surface` | 14.8 | 14.6 |
| `--muted` / `--bg` | 6.1 | 6.5 |
| `--muted` / `--surface` | 5.7 | 5.9 |
| `--muted` / `--surface-2` | 5.4 | 5.2 |
| `--muted` / `--suppressed-bg` | 5.4 | 5.2 |
| `--accent-fg` / `--accent` | 5.2 | 6.1 |
| `--accent` / `--bg` | 5.2 | 6.1 |
| `--high` / `--high-bg` | 4.56 | 6.3 |
| `--moderate` / `--moderate-bg` | 4.52 | 6.3 |
| `--low` / `--low-bg` | 4.55 | 4.9 |
| `--danger` / `--bg` | 5.2 | 5.7 |
| `--danger` / `.error` background (8% mix) | 4.61 | 5.3 |

### `styles.css`: rule changes

Each rule below replaces the one it names; other rules stay as they are apart from the `--panel`
renames.

**Renames.** Every `var(--panel)` becomes `var(--surface)`: `code`, `.top`, `.chip`, `.criterion`,
`.card`, `.panel` and the selected tab.

**Headings and type.** Replace each `font-size` with a token pair. No `rem`/`em`/`px` font size
remains outside `:root`.

| Rule | Was | Becomes |
|---|---|---|
| `h1` | `1.15rem` | `font-size: var(--fs-lg); line-height: var(--lh-lg)` |
| `h2` | `1.05rem` | `var(--fs-lg)` / `var(--lh-lg)` |
| `h3` | `.95rem` | `var(--fs-md)` / `var(--lh-md)` (no longer smaller than body text) |
| `.hint`, `.sub`, `.typeahead .field`, `.cid`, `figcaption` | `.85-.9rem` | `var(--fs-sm)` / `var(--lh-sm)` |
| `.legend`, `.barlabel` | `.85rem` | `var(--fs-xs)` / `var(--lh-xs)` (§2: legends, axis labels) |
| `.big` | `1.8rem` | `var(--fs-2xl)` / `var(--lh-2xl)` (the hero size is item 3) |

`h1, h2, h3 { margin: 0 0 .5rem; line-height: 1.25; }` loses `line-height: 1.25`, because each
heading now sets its own.

**Base controls** (replaces line 23-25):

```css
button, select, textarea, input:not([type="checkbox"], [type="radio"]) {
  font: inherit; color: inherit; background: var(--bg);
  border: 1px solid var(--line); border-radius: 6px; padding: var(--s1) var(--s3);
}
button, select, input:not([type="checkbox"], [type="radio"]) { min-height: 36px; }
button, .btn-secondary { background: var(--surface); cursor: pointer; }
button:hover:not(:disabled) { background: var(--surface-2); }
button:disabled { cursor: not-allowed; opacity: .55; }
.btn-primary { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); font-weight: 600; }
.btn-primary:hover:not(:disabled) { background: color-mix(in srgb, var(--accent) 85%, var(--fg)); }
.btn-tertiary { background: transparent; border-color: transparent; color: var(--accent); padding-inline: var(--s1); }
.btn-tertiary:hover:not(:disabled) { background: transparent; text-decoration: underline; }
.btn-icon {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 28px; min-height: 28px; padding: 0; border-color: transparent; background: transparent; color: var(--muted);
}
.btn-icon:hover:not(:disabled) { background: transparent; color: var(--danger); }
```

- Checkboxes and radios leave the base rule and keep their native look. Today the rule gives them
  a border and padding that browsers mostly ignore.
- `textarea` gets the font, colour, border and padding but no `min-height`; its `rows` sets its
  height.
- `button` has specificity (0,0,1) and each `.btn-*` class (0,1,0), so the classes override the
  base fill. Each `.btn-*:hover:not(:disabled)` (0,3,0) overrides
  `button:hover:not(:disabled)` (0,2,1).
- `.btn-secondary` is listed with `button` so that a non-button element can carry it too.

**Existing controls that the 36px minimum would distort:**

- `.chip button` keeps its rule and adds `min-height: 24px; min-width: 24px;`, so chips stay
  pill-sized. 24×24 is the WCAG 2.2 minimum (review 3.1).
- `.tabs button` adds `background: var(--bg)` and changes `border-radius` to `6px 6px 0 0`. The
  selected tab keeps `background: var(--surface)`, so the selected tab still differs from the
  others. Item 7 restyles the tabs.
- `.typeahead li[aria-selected="true"]` uses `color: var(--accent-fg)` instead of `var(--bg)`.

**`.sr-only`** (replaces line 29):

```css
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
```

**`.error`** (replaces line 45):

```css
.error { background: color-mix(in srgb, var(--danger) 8%, var(--bg)); color: var(--danger); padding: var(--s2) var(--s3); border-radius: 6px; margin: 0 0 .75rem; }
```

Compare's inline `<span class="error">` gets the same tint.

**Tier pill** (replaces lines 76-77):

```css
.tier { display: inline-block; font-weight: 600; font-size: var(--fs-xs); line-height: var(--lh-xs); padding: 2px var(--s2); border-radius: 999px; }
.tier-high { color: var(--high); background: var(--high-bg); }
.tier-moderate { color: var(--moderate); background: var(--moderate-bg); }
.tier-low { color: var(--low); background: var(--low-bg); }
```

**Suppressed hatch** (replaces lines 111-116; the comment line stays):

```css
.bar.hatched, .vbar.hatched, .swatch.hatched {
  background-color: var(--suppressed-bg);
  background-image: repeating-linear-gradient(45deg, var(--suppressed-stripe) 0 2px, transparent 2px 6px);
}
td.hatched {
  background-color: var(--suppressed-bg);
  background-image: repeating-linear-gradient(45deg, color-mix(in srgb, var(--suppressed-stripe) 35%, transparent) 0 2px, transparent 2px 6px);
}
```

- `currentColor` no longer appears in `styles.css`. It is what made the dark stripes near-white.
- Table cells use a 35% stripe so that the muted "<5" text stays readable over the stripes. On a
  stripe it is 3.7:1 (dark) and 4.0:1 (light); between the stripes it is 5.2:1 or better. Today
  it is about 3.8:1 over the 25% `--fg` stripes.

**Coarse pointers**. This rule goes at the end of the file, so it comes after `.chip button` and
`.btn-icon` and wins at equal specificity:

```css
@media (pointer: coarse) {
  button, select, input:not([type="checkbox"], [type="radio"]), .chip button, .btn-icon { min-height: 44px; }
  .chip button, .btn-icon { min-width: 44px; }
}
```

**Comments in `styles.css`** must not contain `#` followed by three or more hex characters (for
example an issue reference like `#102`). The hex check below would flag it.

### `web/src/styles.test.ts` (new)

The test follows `policy.test.ts`: it reads the file with `readFileSync` from `node:fs` and uses
`import.meta.dir`, and needs no new dependency. Helpers:

```ts
const css = readFileSync(join(import.meta.dir, "styles.css"), "utf8");
const ROOT = /:root\s*\{([^}]*)\}/g;
const tokens = (block: string): Record<string, string> =>
  Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const [light, dark] = [...css.matchAll(ROOT)].map((m) => tokens(m[1]));
// WCAG 2.x relative luminance and contrast ratio for #rrggbb
const lum = (hex: string) => { /* sRGB → linear, 0.2126 R + 0.7152 G + 0.0722 B */ };
const contrast = (a: string, b: string) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
```

Tests (one `test()` each):

1. **Two `:root` blocks.** `css.matchAll(ROOT)` finds exactly two, light and dark.
2. **No raw hex colour outside `:root`.** `css.replace(ROOT, "")` does not match
   `/#[0-9a-fA-F]{3,8}\b/`. The same holds for every non-test `.ts`/`.tsx` file in `src/`, listed
   the way `policy.test.ts` lists them.
3. **Every token used is defined.** Every `var(--name)` in `styles.css` is a key of `light`. This
   catches a leftover `--panel` or `--err-bg`. Every `light` value that is a hex colour is also
   defined in `dark`.
4. **Contrast.** For each pair in the table above except the `.error` row (`--fg/--bg`,
   `--fg/--surface`, `--muted/--bg`, `--muted/--surface`, `--muted/--surface-2`,
   `--muted/--suppressed-bg`, `--accent-fg/--accent`, `--accent/--bg`, `--high/--high-bg`,
   `--moderate/--moderate-bg`, `--low/--low-bg`, `--danger/--bg`), `contrast(theme[a], theme[b])`
   is at least 4.5 in both themes. The failure message names the theme and the pair.
5. **The textarea is proportional.** The selector of the rule that contains `font: inherit`
   includes `textarea`. Match it with `/([^{}]+)\{[^}]*font:\s*inherit/`.
6. **Suppressed hatch is quiet.**
   - `currentColor` does not appear in `css`.
   - The `.vbar.hatched` rule and the `td.hatched` rule both contain `var(--suppressed-stripe)`
     and `var(--suppressed-bg)`.
   - `lum(dark["--suppressed-stripe"]) < 0.3`. Today's near-white `#e6edf3` is about 0.84.
7. **Tier colours are semantic.**
   - In both themes `--moderate` differs from `--accent` and `--bar`, and `--low` differs from
     `--danger`.
   - For each of `high`, `moderate` and `low`, the `.tier-<t>` rule contains `var(--<t>)` and
     `var(--<t>-bg)`.
8. **Controls.**
   - `.sr-only` contains `margin: -1px`, `padding: 0` and `border: 0`.
   - `css` contains `min-height: 36px` and a `@media (pointer: coarse)` block with
     `min-height: 44px`.
   - `.btn-primary`, `.btn-secondary`, `.btn-tertiary` and `.btn-icon` each appear as a selector.

To find a rule body by its selector, use a small helper:
`const rule = (sel: string) => css.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[^{]*\\{([^}]*)\\}"))?.[1] ?? ""`.

### `web/src/answer.test.tsx`: one new test

`test("the accrual tier renders as a pill class per tier", …)`, using the existing `render` and
`result` helpers. The options window is 2023-2026, which is four years.

| `patients` | Accrual a year | Expected in the HTML |
|---|---|---|
| `400` | 100 | `class="tier tier-high"` and `>High<` |
| `60` | 15 | `class="tier tier-moderate"` and `>Moderate<` |
| `8` | 2 | `class="tier tier-low"` and `>Low / pilot<` |

## Acceptance criteria

- [ ] (a) The feasibility textarea is in the base control rule (`font: inherit`), so its text is
      proportional, not monospace (styles test 5; screenshot 04 is checked by the orchestrator
      after merge).
- [ ] (b) In dark mode the suppressed hatch is `--suppressed-stripe` (`#656c76`) over
      `--suppressed-bg`, not `currentColor`/near-white (styles test 6; screenshot 08).
- [ ] (c) Moderate is amber (`--moderate` with `--moderate-bg`) and Low / pilot is orange
      (`--low` with `--low-bg`), each as a tinted pill. Neither equals `--accent`, `--bar` or
      `--danger` (styles test 7, answer tier test).
- [ ] (d) No raw hex colour appears in `styles.css` outside the two `:root` blocks, or in any
      non-test source file (styles test 2).
- [ ] (e) The existing tests pass. `bun run typecheck` and `bun test` are green.
- [ ] Every `var(--…)` used is defined, and every colour token has a dark value (styles test 3).
- [ ] All the listed text/background pairs are ≥ 4.5:1 in both themes (styles test 4).
- [ ] The base size is 16px, and every `font-size` outside `:root` is a `var(--fs-*)` token.
- [ ] `.btn-primary`, `.btn-secondary`, `.btn-tertiary` and `.btn-icon` exist, and a plain
      `button` has the secondary look (`--surface` fill, `--line` border).
- [ ] Buttons, selects and text inputs are at least 36px tall, and at least 44px under
      `(pointer: coarse)`. Chip "×" buttons are at least 24×24 (44×44 coarse). `.sr-only` is the
      standard clip pattern (styles test 8).
- [ ] `git diff --stat` touches only `web/src/styles.css`, `web/src/styles.test.ts` and
      `web/src/answer.test.tsx`, plus this spec.

## Test plan

```bash
cd web && bun install --frozen-lockfile && bun run typecheck && bun test
```

- The new `styles.test.ts` checks 1-8 run on the CSS file itself. They need no DOM and no
  network.
- The new tier test in `answer.test.tsx` renders `Answer` with `renderToStaticMarkup` from
  synthetic `CountResult`s (counts 400, 60 and 8 over a 2023-2026 window), like the existing
  tests in that file.
- Existing tests: `answer.test.tsx`, `app.test.tsx`, `builder.test.tsx`, `compare.test.tsx`,
  `cohort.test.ts`, `policy.test.ts` and `transport.test.ts` pass unchanged. This item changes no
  markup, and these tests don't read CSS.
- `uv run pytest -q` is n/a: no Python or API model changes. The dashboard check is n/a: nothing
  under `dashboard/` changes.
- No test reads `$DATA`, the de-id file, the PHI file or `$DATA/raw/`.
- Visual check (orchestrator, dev server after merge): screenshots 04 and 08 at 1440px in light
  and dark, and at 390px.

## Risks

- **Bar contrast.** §2's `--bar` (`#54aeff` light) is about 2.4:1 against white, below the
  3:1 that WCAG 1.4.11 asks of graphics. `--bar-partial` is lighter still. The bars aren't the
  only carrier of the number: every bar has its count label, and the sr-only table has the
  values. The review chose lighter bars so that they don't compete with the controls. This spec
  keeps the §2 values and doesn't test them against 3:1. Item 4 (charts) can darken them if the
  screenshots read poorly.
- **Thin margins.** High, Moderate and Low in light mode sit at 4.52-4.56:1, just above 4.5. The
  contrast test fails if anyone nudges these tokens.
- **Larger base size.** Going from 15px to 16px, with 36px controls, makes the page about 7%
  larger and the header taller until item 2 reworks it. Expect wider wrapping at 390px in this
  interim state. That is acceptable because items 2-7 follow directly (run order #97 → #98…).
- **Native checkboxes.** Checkboxes and radios now render natively, because they leave the base
  rule. Their look changes slightly in the Breakdown and Compare fieldsets.
- **`color-mix()` and `:not()` with a selector list** need Chrome 111, Safari 16.2 or Firefox 113,
  or later. `color-mix` is already in use (`td.hatched`), so this raises no browser floor.
- **CSS regex tests are brittle by design.** They pin selectors and token names. A later item that
  renames `.tier-*` or the hatch selectors must update `styles.test.ts` in the same change.
