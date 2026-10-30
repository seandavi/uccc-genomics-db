# Discover UI/UX review, 2026-10-30

Commissioned by Sean ("useful, but it doesn't lead the eye, has some confusing spots (like empty input boxes), and is not very aesthetically pleasing"). Written by a reviewer agent from screenshots of the dev site (kept on the pipeline host, not in the repo: they show floored real counts) and the `web/` source. Owner decisions (2026-10-30): remove the Assistant column until chat ships (2.5); future years from date-shifting are handled in copy ("dates are shifted for de-identification; the last years are partial"), not by clamping (2.10); proceed with all items. Item 8 (share links pasted into an open tab) was added by the orchestrator. The four `03-cohort-*` screenshots referenced below show the landing state because of a capture-script bug, not an app bug (and item 8).

---


## Summary

Discover gives correct answers. The trouble is that every element is drawn with about the same weight, so nothing on the page stands out. The header is a row of identical outlined controls, and the patient count, which is the answer, is the same size as the card labels next to it. The landing page shows a full answer for "all patients" with no guidance on what to do next. Inputs have no placeholders. The accrual chart scrolls sideways out of view, sits on uneven baselines, and draws suppressed years taller than small years that are shown. Most fixes are CSS and copy changes. None of them touch the definition and operations model, the share link or suppression. The plan below has seven work items.

**How I reviewed it.** I looked at all ten screenshots. I read `App.tsx`, `Builder.tsx`, `Answer.tsx`, `Compare.tsx`, `cohort.ts` and `styles.css`, plus `COHORT_DISCOVERY.md` §3.3 and `cohort/suppress.py` / `definition.py` to check two behaviours.

**Caveat on the screenshots.** The four `03-cohort-*-light.png` shots show the *empty* landing state (no population chips, no criteria, an "all patients" answer), not the NSCLC/KRAS cohort they were supposed to show. My built-cohort evidence comes from `06-mobile-cohort.png` and `08-cohort-accrual-dark.png`. Retake the 03 set before using it as a "before" baseline. I did not check whether the cause was the capture script or a share-hash restore problem.

---

## 1. Top problems, prioritized

### P1: the page has no focal point and doesn't lead through the task

**1.1 The patient count isn't the hero, and the three cards are equal**
- **Seen in:** 01, 03-*, 06, 08.
- **Code:** `Answer.tsx:29-50` (`Cards`), `styles.css:68-74` (`.cards` auto-fit, `.big { font-size: 1.8rem }`), `styles.css:18-21` (h1 1.15rem, h2 1.05rem, h3 .95rem on a 15px base).
- **What a user experiences:**
  - The only large type on the page is three equal numbers: patients, accrual and share.
  - The section headings ("Population", "Answer", "Funnel") are barely bigger than body text. "Funnel" (h3, .95rem) is actually *smaller* than body text.
  - The eye has nowhere to land first. On the landing page it often lands on the bright solid funnel bar, which says nothing.
- **Fix:**
  - Make Patients a hero card spanning about half the answer width, with a 44px number.
  - Make Accrual and Share secondary cards at 28px.
  - Name the denominator and the window under each number (see 2.3).
  - Adopt the type scale in §2.

**1.2 The header is a flat row of equal controls, and it shows a raw hash next to "Version"**
- **Seen in:** 01-05, 08; 06 (where it wraps to four rows).
- **Code:** `App.tsx:158-176`, `styles.css:31-33`.
- **What a user experiences:**
  - "Discover", the name input, "Version [v1]", a monospace hash, "Share link", "Compare" and "Feasibility statement" all have the same border, weight and spacing.
  - None of them is the primary action.
  - The `cohort_id` (`App.tsx:169`) starts with `v1-` because that is the **schema** version (`definition.py:469`). In 08 the Version select reads **v2** right next to a hash that starts **v1-**. That reads as a contradiction.
  - "Version" doesn't say whether versions are saved, shared or local. In fact each one is an automatic edit-history step held in local storage.
- **Fix:**
  - Move the cohort id out of the header into a "Details" line inside the share popover and the Data notes tab, labelled "Cohort ID (for support)".
  - Rename the Version select to **History**, with option text like `Edit 3 · <short definition>`. Add ↶/↷ buttons that step through `hist.current`. This uses the same `setHist` as the select does today, so the ops model doesn't change.
  - Make **Feasibility statement** the single primary button, because it is the deliverable.
  - Make Share and Compare secondary buttons, right-aligned as a group.

**1.3 The landing page is an answer with no question, and the inputs are blank boxes**
- **Seen in:** 01, and 03-* in practice.
- **Code:**
  - `Builder.tsx:45-56`: the typeahead `<input>` has no `placeholder`.
  - `Builder.tsx:456`: "Add criterion".
  - `Builder.tsx:157`: the population typeahead with `minChars={0}`.
  - `Answer.tsx:47`: "100% of N patients (all patients)".
  - `Answer.tsx:54-73`: a funnel with one row.
- **What a user experiences:**
  - The left column is a heading, six small "+ …" buttons, two "All years" selects, an unchecked checkbox about "same report" with no criteria yet, a bold label and an **empty box with no hint of what it accepts**. The owner named exactly this ("empty input boxes").
  - The answer column shows a share of 100% (meaningless), a one-row "Funnel" drawn as a full-width solid bar, and a chart.
  - The far-right column says "Coming later".
  - Nothing invites the first action.
- **Fix:**
  - Add placeholders: "Search genes, biomarkers, IHC, specimens… e.g. KRAS, TMB, PD-L1" for Add criterion, and "Search tumor types… e.g. NSCLC" for the tumor-type adder.
  - When the definition is empty, replace the funnel and the share card with a **guided start**: a one-line "how this works" and three to five example cohorts as clickable cards.
    - Examples are synthetic definitions in code, applied through `transport.apply` exactly the way a share link is.
    - Show **no counts** on the example cards. Counts appear only after an example is applied, through the normal suppressed `/count` path, so this adds no new output path.
  - Keep the whole-population total as one context line ("Discover covers {floored total} patients sequenced by Caris and FMI").
  - Hide "All criteria on the same report" until there are two or more criteria (see 2.6).

**1.4 The accrual chart scrolls out of view, misaligns, and draws suppressed bars taller than shown ones**
- **Seen in:** 01 and 03-accrual (the last visible year label is cut off at the right edge and later years are off-screen); 08 (two partial-year bars float above the baseline); 01 (hatched "<5" bars are taller than the bar of a nearby small *shown* year).
- **Code:** `styles.css:94-99` (`.bars` has `overflow-x: auto`, `.col` has `min-width: 2.5rem`, and `.barlabel` has variable height); `Answer.tsx:105-121` (hatched bars are drawn at a fixed `"12%"` height while shown bars use `Math.max(2, …)`); `Answer.tsx:119` ("partial year" adds a third label line).
- **What a user experiences:**
  1. **The most recent years are hidden.** They are the ones a feasibility reader cares about most, and only a horizontal scroll reveals them. Overlay scrollbars give no hint that the chart scrolls.
  2. **Baselines differ.** Partial years have a taller label stack, so their `barbox` is shorter and the bar sits higher. It reads as more patients.
  3. **Suppressed reads as bigger than shown.** A "<5" bar at 12% is taller than a shown year at 2%. That misreads the data even though no number leaks.
  4. **Missing years vanish from the axis.** `suppress.py:195-201` emits only years with patients, and the bars render consecutively. In 06 and 08 the year sequence silently skips a year.
- **Fix** (CSS grid plus small JSX changes in `AccrualTab`):
  - Use `grid-template-columns: repeat(N, minmax(0, 1fr))` and never scroll. When N > 12, use two-digit year labels ('15) or label every other year.
  - Give the label row a fixed height (`grid-template-rows: 1fr auto` with a fixed label height). Mark partial years with the lighter bar plus an asterisk, and add one legend line ("* partial year") instead of a third label line.
  - Draw a suppressed bar at the height a count of `min_cell` would have (`min_cell / max`), with a floor of 2%. The bar still reads "<5" and stays hatched, so it shows only the public upper bound and is never taller than a shown bar of `min_cell` or more. Apply the same rule to funnel bars (`Answer.tsx:65`, a fixed `8%` today).
  - Fill missing years between the first and last year with an empty slot labelled "–", and add a legend line "–: no patients that year". This tells the user nothing new: the gap is already visible today, and Compare already says "Blank: no patients that year" (`Compare.tsx:60`). The issue should still carry `review:security` because it changes an output view.
  - When *every* year is suppressed (06), shrink the chart to a single hatched strip with "Every year under 5". Today it is a tall empty box with a row of bars at the bottom.

### P2: confusing spots, inconsistent controls, weak colour semantics

**2.1 The suppressed hatch is the loudest thing on the page in dark mode**
- **Seen in:** 08.
- **Code:** `styles.css:112-115` (the stripes use `currentColor`, which is `--fg #e6edf3`, on `#2c4a73`).
- **What a user experiences:** The near-white diagonal stripes out-shout the real data. Suppressed should read as *unknown and quiet*, not as an alarm.
- **Fix:** Add `--suppressed-stripe` and `--suppressed-bg` tokens (see §2). Use muted grey stripes on a panel-tinted background in both themes. They stay hatched, so they are still distinguishable in greyscale, and the "<5" text stays.

**2.2 Tier colours aren't semantic, and "Moderate" uses the same blue as the accent and the bars**
- **Code:** `styles.css:5,13,77`. `--moderate` is `#1a5fb4` (light) and `#79b8ff` (dark, identical to `--accent`).
- **What a user experiences:**
  - "High" is green and "Low / pilot" is error red, which reads like a validation failure.
  - "Moderate" looks like a link.
  - The tier is coloured text only, so it is easy to miss.
- **Fix:**
  - Use semantic tokens: success green, attention amber and a "caution" orange-red for low (§2).
  - Render the tier as a pill (tinted background with a text label) and keep the `title` description.
  - Optionally add a tiny three-step meter.

**2.3 Jargon and copy problems**
- **Code:** `Answer.tsx:57` "Funnel"; `Answer.tsx:21` "∧"; `Builder.tsx:370` `c1`/`c2`; `Builder.tsx:386-388` "Or…"/"Then…"; `Answer.tsx:269` "Answer"; `Builder.tsx:162-171` "From [All years] To [All years]"; `Answer.tsx:40` "Accrual a year" with no window.
- **What a user experiences:**
  - "∧" is logic notation: screen readers read it as "logical and", and clinicians don't use it.
  - "c1" is an internal id.
  - "No KEAP1 or STK11 alteration" next to a select reading "Exclude" (08) is a double negative.
  - "Or…" and "Then…" don't say what they add.
  - Accrual a year is divided over the whole data window (`cohort.ts` `accrualPerYear`), which includes partial years and years before the cohort's first report. Nothing on screen says which window.
- **Fix:**
  - "Funnel" → **"How each criterion narrows the cohort"**.
  - Step prefixes: "+ " for include, "− " for exclude, and "+ tested negative: " for tested negative.
  - Remove the visible `cid` and keep it in aria labels.
  - Card label: drop the "no" prefix inside the card, since the mode badge carries it. Keep `criterionLabel` with the "no" prefix for the funnel and the statement.
  - "Or…" → **"+ Or another"**. "Then…" → **"+ Later report"**, with `title`s explaining each.
  - "Answer" → the cohort name or "Your cohort".
  - The year selects become "Years [Any ▾] – [Any ▾]".
  - The Accrual card subline gets "per year, {from}–{to}".
- **Tests:** these strings are pinned in `builder.test.tsx:41-81` and `answer.test.tsx:172`, so the tests need updating.

**2.4 Buttons, chips, selects and tabs all look the same**
- **Code:** `styles.css:23` (one style for every `button, select, input`), `styles.css:91-92` (tabs), `Builder.tsx:153` (adders), `Builder.tsx:383-389` (card actions).
- **What a user experiences:**
  - "+ tumor type" (adds a filter), "Edit" (opens an editor), "Remove" (destructive), "Accrual" (a tab) and "Share link" are visually identical.
  - Tabs look like toggle buttons, and the selected tab differs only by a 1px border colour plus bold text.
- **Fix:** apply the button hierarchy in §2:
  - Adders become dashed "ghost chips".
  - Card actions become tertiary text buttons.
  - Remove becomes an icon "✕" button with `aria-label` and a red hover.
  - Tabs get a 2px accent underline and no box.

**2.5 The empty Assistant column takes about 280px at 1200px and wider**
- **Seen in:** 01-05, 08.
- **Code:** `App.tsx:192-195`, `styles.css:37-41`.
- **What a user experiences:** A grey "Coming later" note takes a fifth of the width. It squeezes the chart (and worsens 1.4) and pulls the eye to the top right.
- **Fix:** Remove the column until the assistant ships, and give the answer column the space. If the owner wants the signpost, use a one-line muted footer link instead. (§3.3 says phase 1 leaves the column empty. This reprices that choice; it is the owner's call.)

**2.6 "All criteria on the same report" shows before there are criteria, above the input that adds them**
- **Code:** `Builder.tsx:450-455`.
- **Fix:** Render it only when `d.criteria.length >= 2` (or when it is already checked, so the state stays visible). Move it *below* the cards as a scope toggle reading "Match all criteria on the same report", with the existing disabled reason shown as visible hint text rather than only as a `title`.

**2.7 Typeahead options look alike, and the kind label is faint and far away**
- **Seen in:** 02 (two "KRAS" rows; the expression row ranks above the gene alteration row).
- **Code:** `Builder.tsx:59-63`, `styles.css:66-67`, `cohort.ts` `FIELD_LABELS`.
- **What a user experiences:** Two identical names, with the distinguishing kind in small low-opacity text at the far right edge. Most users mean the alteration.
- **Fix:**
  - Put a kind **badge** on the left, before the value, with plain words: "Gene alteration", "RNA expression", "IHC", "Biomarker", "Tumor type", "Data available".
  - Keep the server's ranking (no counts, by design).
  - Separately, ask the ranking owner whether `alteration.gene` should outrank `expression.gene` for exact gene matches. That is a server change, out of scope for the UI items.

**2.8 The feasibility statement renders in monospace in a raw textarea that pushes the page down**
- **Seen in:** 04.
- **Code:** `styles.css:23` (`textarea` is missing from the `font: inherit` selector, so the browser default monospace applies); `App.tsx:18-32`.
- **What a user experiences:** The grant paragraph looks like code, has no heading, and has two equal buttons.
- **Fix:**
  - Add `textarea` to the base control rule.
  - Give the panel a heading ("Feasibility statement for grant text").
  - Show the paragraph in a readable 65ch block.
  - Make **Copy** the primary button.
  - Keep the read-only textarea, which tests pin in `app.test.tsx:12,18`.
  - Show it as an anchored panel under the header button, not a full-width band.

**2.9 Compare opens with a single version and a dead "Count" button**
- **Seen in:** 05.
- **Code:** `Compare.tsx:79-91`, `App.tsx:173`.
- **Fix:**
  - When `versions.length < 2`, disable the header button and give it visible helper text ("Make a change to compare versions") instead of opening a panel with a disabled button.
  - Rename "Count" to "Compare selected".

**2.10 A future year can appear in the chart and in the grant statement**
- **Seen in:** 04 (statement window ends in a year that is still to come); 08 (that year appears as a partial-year bar).
- **Code:** `App.tsx:150` passes `options.years` into `feasibility`; date-shift spillover is expected per §3.3.
- **What a user experiences:** A grant paragraph says sequencing happened in a year that hasn't happened yet.
- **Fix:** This needs an owner decision. Either clamp the *displayed* window end to the current year in the copy and statement, or say "dates are shifted for de-identification; the last years are partial". The second is a copy-only change.

**2.11 Breakdown and Pivot open on empty controls**
- **Seen in:** 03-breakdown, 03-pivot.
- **Code:** `Answer.tsx:140-163`, `Answer.tsx:183-206`.
- **What a user experiences:**
  - Breakdown shows a box of eight unchecked checkboxes and nothing else.
  - Pivot shows two very wide "none" selects and "Choose rows and columns."
- **Fix:**
  - Add one-line purpose text to each.
  - Pivot select placeholders become "Choose…", with a max width of about 16rem.
  - Add two or three "suggested pairs" buttons, such as "Tumor type × Year", that call the existing `choose()`.
  - Breakdown checkboxes become toggle chips.

**2.12 Mobile: the answer is far below the fold, and the header takes four rows**
- **Seen in:** 06.
- **Code:** `styles.css:31-33,42`.
- **What a user experiences:**
  - The cohort name is truncated by `min-width: 16rem`.
  - Three wrapped header rows of buttons come before any content.
  - The patient count sits below the whole builder.
  - Funnel bars are squeezed to slivers by the `minmax(8rem,14rem) 5rem 1fr` grid (`styles.css:83`).
- **Fix:**
  - Header: name on its own line, with History plus a "⋯" menu holding Share, Compare and Statement.
  - Add a **sticky bottom summary bar** with the patient count, the tier pill and a "View" link that jumps to `#answer-h`.
  - Below 600px, stack the funnel's label above its number and bar.

### P3: polish and accessibility basics

- **3.1 Touch targets.** Chip "×" buttons have `padding: 0 .4rem` (`styles.css:52`), which comes out around 20px tall. That is below the WCAG 2.2 minimum of 24×24 CSS px. Make them at least 24px, and 44px on touch devices via `@media (pointer: coarse)`.
- **3.2 `.sr-only`** (`styles.css:29`) lacks `margin:-1px; padding:0; border:0`. Use the standard clip pattern.
- **3.3 Busy dimming.** `.dim { opacity: .55 }` (`styles.css:103`) drops muted text below 4.5:1 while counting. Use a thin progress bar under the header and `opacity: .75` instead.
- **3.4 Disabled buttons** use only `opacity: .55` with no reason given (Feasibility while stale, Compare's Count). Add visible helper text or `aria-describedby`.
- **3.5 Accrual precision.** `toFixed(1)` everywhere. Use one decimal below 10 and whole numbers at 10 and above, so values read less spuriously precise.
- **3.6 Data notes are hidden in the last tab.** The caveat that stage, treatment and outcomes aren't in this data matters. Repeat it as a one-line muted footnote under the cards.
- **3.7 Tabular numbers.** Add `font-variant-numeric: tabular-nums` to `.big` and to the chart labels.
- **3.8 Disclosed panels.** Feasibility and Compare render above the whole page and shift the layout (04, 05). Anchor them under the header row, and return focus to the trigger button on Close.

---

## 2. Design direction

**Principles.** One question per screen region: *who* (left), *how many* (centre top), *how they narrow* (centre middle), *over time and by what* (tabs). One primary action. Suppressed values stay quiet but are never ambiguous. Use the system font stack: no web fonts, so nothing from a CDN. If a branded face is wanted later, self-host a woff2 under `web/public/` with `@font-face`.

### Type scale (16px base, 1.25 ratio, rounded)

| Token | Size / line height | Use |
|---|---|---|
| `--fs-xs` | 12 / 16 | badges, legends, axis labels |
| `--fs-sm` | 13 / 18 | sublines, helper text, typeahead kind |
| `--fs-md` | 16 / 24 | body, controls |
| `--fs-lg` | 18 / 26 | section titles (WHO / WITH / How it narrows) |
| `--fs-xl` | 22 / 28 | cohort name in header |
| `--fs-2xl` | 28 / 32 | secondary metrics (accrual, share) |
| `--fs-hero` | 44 / 48 | patient count |

Weights: 400 for body, 600 for titles and metric numbers. Section titles are 600, uppercase `--fs-xs` with letter-spacing .06em for eyebrow labels (WHO, WITH), and `--fs-lg` for real headings.

### Spacing (4px grid)

`--s1 4 · --s2 8 · --s3 12 · --s4 16 · --s5 24 · --s6 32 · --s7 48`

- Columns are separated by `--s6`, sections by `--s5`, and items inside a card by `--s2`/`--s3`.
- Page max-width is 1280px, centred.
- Builder column is 22rem; the answer column takes the rest.

### Colour tokens

The values follow GitHub Primer's AA-designed palette. Check each text/background pair at ≥4.5:1 with a contrast checker when implementing; I did not measure them.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#ffffff` | `#0d1117` | page |
| `--surface` | `#f6f8fa` | `#161b22` | cards, header |
| `--surface-2` | `#eef1f4` | `#21262d` | hover, selected chip |
| `--fg` | `#1f2328` | `#e6edf3` | text |
| `--muted` | `#59636e` | `#9198a1` | secondary text |
| `--line` | `#d1d9e0` | `#3d444d` | borders |
| `--accent` | `#0969da` | `#4493f8` | **the one accent**: primary button, focus, selected tab, links |
| `--accent-fg` | `#ffffff` | `#0d1117` | text on accent |
| `--bar` | `#54aeff` | `#388bfd` | data bars (lighter than accent so bars don't compete with controls) |
| `--bar-partial` | `#b6e3ff` | `#1f3a5f` | partial-year bars |
| `--high` / `--high-bg` | `#1a7f37` / `#dafbe1` | `#3fb950` / `#12261e` | tier High pill |
| `--moderate` / `--moderate-bg` | `#9a6700` / `#fff8c5` | `#d29922` / `#272115` | tier Moderate pill |
| `--low` / `--low-bg` | `#bc4c00` / `#fff1e5` | `#db6d28` / `#2a1b14` | tier Low / pilot pill (orange, not error red) |
| `--danger` | `#d1242f` | `#f85149` | errors, destructive hover only |
| `--suppressed-bg` | `#eef1f4` | `#21262d` | hatched fill background |
| `--suppressed-stripe` | `#8c959f` | `#656c76` | hatch stripes (quiet, greyscale-safe) |

**Suppressed rule.** Every suppressed value is the text "<5" (italic, `--muted`) plus a hatch with `repeating-linear-gradient(45deg, var(--suppressed-stripe) 0 2px, transparent 2px 6px)` over `--suppressed-bg`. It is never blank and never 0. "–" is used *only* for a true empty year slot and for "not computable", and each use has a legend.

### Shape and elevation
- Radius: 6px for controls, 10px for cards and panels, 999px for chips and pills.
- Borders: 1px `--line` on cards and inputs. There are no borders on tabs or on tertiary buttons.
- Shadow: none on cards. `0 8px 24px rgb(0 0 0 / .12)` only on floating layers (the typeahead list, the ⋯ menu, the share popover).
- Focus: a 2px `--accent` outline with a 2px offset (keep the existing rule).

### Controls

| Level | Look | Where |
|---|---|---|
| Primary | filled `--accent`, `--accent-fg` text, 36px tall | one per view: header "Feasibility statement"; "Copy" in its panel; "Apply" on the guided start |
| Secondary | `--surface` fill, 1px `--line`, 36px | Share, Compare, Save/Cancel in editors |
| Tertiary | text only in `--accent`, underline on hover | Edit · + Or another · + Later report · Drop |
| Icon | 28px square (44px on coarse pointers), ✕, `--muted` → `--danger` on hover | remove chip, remove criterion |
| Filter chip | pill, `--surface-2`, value + ✕ | applied population values |
| Adder chip | pill, dashed `--line`, "+ Tumor type" | add a population filter |
| Tabs | text, `--muted`; selected = `--fg` + 2px `--accent` underline | Accrual / Breakdown / Pivot / Data notes |
| Select / input | 36px, 6px radius, **always a placeholder or "Any"** | everywhere |

### Desktop wireframe: built cohort

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Discover  │ KRAS NSCLC, no STK11/KEAP1 ✎        ↶ ↷  History: Edit 3 ▾      [Share] [Compare] [■ Feasibility statement] │
├────────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ WHO                            │ ┌───────────────────────────────┐ ┌──────────────┐ ┌───────────┐ │
│ [NSCLC ✕]  [years ✕]           │ │ PATIENTS                      │ │ PER YEAR     │ │ SHARE     │ │
│ (+ Tumor type)(+ Organ)(+ Sex) │ │ ██ hero number (44px)         │ │ x.x          │ │ nn%       │ │
│ (+ Age)(+ Vendor)(+ Assay)     │ │ in N reports                  │ │ (Low/pilot)  │ │ of N NSCLC│ │
│ Years [Any ▾] – [Any ▾]        │ │                               │ │ yyyy–yyyy    │ │ patients  │ │
│                                │ └───────────────────────────────┘ └──────────────┘ └───────────┘ │
│ WITH                all match  │ Not in this data: stage, treatment, outcomes, race, ethnicity.   │
│ ┃ INCLUDE  KRAS alteration  ▾  │                                                                 │
│ ┃ Edit · + Or another ·        │ HOW EACH CRITERION NARROWS THE COHORT                          │
│ ┃ + Later report           ✕   │ NSCLC                         nnn ██████████████████████████    │
│ ┃ EXCLUDE  KEAP1 or STK11 alt ▾│ + KRAS alteration              nn ██████                        │
│ ┃ Edit · + Or another      ✕   │ − KEAP1 or STK11 alteration    nn ███▌                          │
│                                │ ▨ <5  fewer than 5, or hidden so a small count can't be derived │
│ ┌────────────────────────────┐ │                                                                 │
│ │⌕ Add a gene, biomarker,    │ │  Accrual   Breakdown   Pivot   Data notes                       │
│ │  IHC, specimen… e.g. TMB   │ │  ━━━━━━━                                                        │
│ └────────────────────────────┘ │  ▁ ▂ ▃ ▅ ▆ ▇ █ ▇ █ ▒*  (every year fits; '15 '16 … labels)      │
│ ☐ Match all criteria on the    │  * partial year   – no patients that year   ▨ <5                │
│   same report  (≥2 criteria)   │                                                                 │
└────────────────────────────────┴─────────────────────────────────────────────────────────────────┘
```
The include/exclude stripe on the left of each card is green for include and a muted orange for exclude. It doubles the mode select, so the select becomes a small badge-style select.

### Desktop wireframe: landing (empty definition)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Discover  │ Untitled cohort ✎                                  [Share] [Compare·] [Feasibility·] │
├────────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ WHO                            │  How many of our sequenced patients fit your study?            │
│ (+ Tumor type)(+ Organ)(+ Sex) │  Pick who (left), add criteria, then copy a feasibility         │
│ (+ Age)(+ Vendor)(+ Assay)     │  statement. Counts under 5 show as <5.                          │
│ Years [Any ▾] – [Any ▾]        │                                                                 │
│                                │  START FROM AN EXAMPLE                                          │
│ WITH                           │  ┌─────────────────────┐ ┌─────────────────────┐ ┌────────────┐ │
│ ┌────────────────────────────┐ │  │ KRAS G12C in NSCLC  │ │ MSI-high colorectal │ │ HER2-amp   │ │
│ │⌕ Add a gene, biomarker,    │ │  │ NSCLC + KRAS G12C   │ │ CRC + MSI-H         │ │ breast     │ │
│ │  IHC, specimen… e.g. KRAS  │ │  │           [Use →]   │ │           [Use →]   │ │  [Use →]   │ │
│ └────────────────────────────┘ │  └─────────────────────┘ └─────────────────────┘ └────────────┘ │
│                                │  (no counts on examples; counts appear after "Use")            │
│                                │                                                                 │
│                                │  Discover covers {floored total} patients from Caris and FMI.  │
│                                │  Accrual by year ▁▂▃▅▆▇█ (small, muted, context only)           │
└────────────────────────────────┴─────────────────────────────────────────────────────────────────┘
```
"·" marks a disabled button with a visible reason on hover and focus. Compare is disabled until there are two history steps; the statement is disabled until there is a current answer.

### Mobile wireframe (390px)

```
┌──────────────────────────────┐
│ Discover               ⋯     │  ⋯ = Share, Compare, Feasibility statement, History
│ KRAS NSCLC, no STK11/K… ✎    │
│ ↶ ↷  Edit 3 ▾                │
├──────────────────────────────┤
│ WHO                          │
│ [NSCLC ✕]                    │
│ (+ Tumor type)(+ Organ) …    │
│ Years [Any▾] – [Any▾]        │
│ WITH                         │
│ ┃ INCLUDE KRAS alteration ▾  │
│ ┃ Edit · + Or another     ✕  │
│ ┃ EXCLUDE KEAP1 or STK11  ▾  │
│ [⌕ Add a gene, biomarker…]   │
├──────────────────────────────┤
│ PATIENTS  ██ (hero)          │
│ PER YEAR x.x (Low)  SHARE nn%│
│ HOW IT NARROWS               │
│ NSCLC                   nnn  │  label on its own line,
│ ██████████████████████████   │  number + bar below
│ + KRAS alteration        nn  │
│ ██████                       │
│ Accrual  Breakdown  Pivot  … │  tabs scroll horizontally
│ ▒▒▒▒▒▒▒▒ Every year under 5  │
├──────────────────────────────┤
│▌nn patients · (Low)   View ↑ │  sticky bottom summary bar
└──────────────────────────────┘
```

---

## 3. Implementation plan

Each item is issue-sized and in dependency order. All of them are `web/`-only. Every item runs `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` (the dashboard and pytest checks are n/a). "Screenshot" means re-capturing the matching `uxshots` file at 1440px light, 1440px dark and 390px.

### 1. Design tokens and base controls
- **Scope:**
  - Replace the `:root` variables with the §2 token set (light and dark).
  - Base size 16px plus the type-scale tokens and the spacing tokens.
  - Add `textarea` to the base control rule.
  - Add button classes `.btn-primary`, `.btn-secondary`, `.btn-tertiary` and `.btn-icon`. Plain `button` stays secondary.
  - Add the standard `.sr-only`, 36px controls and the coarse-pointer 44px rule.
  - Suppressed hatch tokens; tier pills (`.tier` with `-bg` tokens and "Moderate" in amber).
  - No markup changes beyond the tier pill class.
- **Files:** `web/src/styles.css`; `web/src/Answer.tsx:41-42` (tier pill class).
- **Acceptance:**
  - (a) The feasibility textarea text is proportional, not monospace (04).
  - (b) In dark mode, suppressed hatches are grey stripes, not near-white (08).
  - (c) Moderate is amber and Low is orange, each with a tinted pill background; neither is blue or error red.
  - (d) No raw hex colour outside `:root`.
  - (e) Existing tests pass.

### 2. Layout shell: header, history, assistant column, mobile header and summary bar
- **Depends on:** 1.
- **Scope:**
  - Header: cohort name (`--fs-xl`), then ↶/↷ plus "History: Edit n" (`setHist` over `hist.current`, no ops-model change), then a right-aligned group of Share, Compare and Feasibility statement (`.btn-primary`).
  - Move `cohort_id` out of the header into the share popover ("Cohort ID (for support)") and the Data notes tab.
  - Compare is disabled with a visible reason when there are fewer than two versions.
  - Remove the Assistant column (owner's call, noted in the PR).
  - Max-width 1280px centred grid.
  - At 600px and below: a ⋯ menu for the header actions, and a sticky bottom summary bar showing `<Count>` (so suppressed is "<5" and hatched), the tier pill and a "View" anchor.
- **Files:** `web/src/App.tsx:156-196`, `web/src/styles.css`, `web/src/app.test.tsx`.
- **Acceptance:**
  - (a) No hash is visible in the header at any width.
  - (b) Exactly one filled-accent button in the header.
  - (c) At 1440px the answer column extends to the right edge of the content (no "Coming later" column).
  - (d) At 390px the header is at most two rows, and a summary bar showing the patient count (or "<5") stays visible while scrolling.
  - (e) A test pins that the summary bar renders "<5" for a null count.

### 3. Answer hierarchy and copy
- **Depends on:** 1.
- **Scope:**
  - Hero Patients card at `--fs-hero`; secondary Accrual and Share at `--fs-2xl`.
  - The Accrual subline names the window (`yyyy–yyyy`). One decimal below 10, whole numbers otherwise.
  - Hide the Share card and the funnel when the definition is empty (population and criteria both empty).
  - "Funnel" → "How each criterion narrows the cohort". Step prefixes "+", "−" and "+ tested negative:" replace "∧" (`Answer.tsx:18-22`).
  - "Answer" heading → cohort name or "Your cohort".
  - One-line data-notes footnote under the cards.
  - Tabular numbers.
- **Files:** `web/src/Answer.tsx`, `web/src/styles.css`, `web/src/answer.test.tsx`.
- **Acceptance:**
  - (a) In every answer screenshot the patient number is visibly the largest text on the page.
  - (b) No "∧" anywhere.
  - (c) The empty definition shows no Share card and no funnel.
  - (d) The Accrual card shows its year window.
  - (e) A suppressed patient count still renders "<5" in the hero (test).

### 4. Accrual and funnel charts (label `review:security`)
- **Depends on:** 1.
- **Scope:**
  - Accrual as a CSS grid with N equal columns and no horizontal scroll. Two-digit or alternate year labels when N > 12.
  - Fixed-height label row; partial years marked with "*" and a legend line instead of a third label line.
  - Fill gap years between the first and last year with a "–" slot and the legend "–: no patients that year".
  - Suppressed bar height is `max(2%, min_cell/max)`, applied to `.vbar.hatched` and to the funnel's hatched bar (`Answer.tsx:65,113`).
  - All-suppressed series collapse to a single strip with "Every year under {min_cell}".
  - Keep the `sr-only` table and add the gap years to it as "no patients".
- **Files:** `web/src/Answer.tsx:54-73,105-134`, `web/src/styles.css:83-99,112-116`, `web/src/answer.test.tsx`.
- **Acceptance:**
  - (a) At 1440px every year, including the last, is visible without scrolling (01).
  - (b) All bar bottoms share one baseline, including partial years (08).
  - (c) No hatched bar is taller than a shown bar whose count is `min_cell` or more (01).
  - (d) No year is missing from the axis (06/08).
  - (e) Tests pin that a null year renders "<5" with `.hatched` and never "0" or empty, and that a gap year renders "–" and is never "<5".

### 5. Builder controls and criterion cards
- **Depends on:** 1.
- **Scope:**
  - Typeahead placeholders (a new `placeholder` prop on `Typeahead`; add-criterion and per-dimension texts as in §1.3).
  - Option rows lead with a plain-language kind badge (a `KIND_LABELS` map next to `FIELD_LABELS` in `cohort.ts`).
  - Population adders as dashed adder chips with title-case labels.
  - Year selects read "Years [Any] – [Any]".
  - Criterion cards:
    - Mode stripe and badge-style select.
    - The `cid` is hidden visually but kept in aria labels.
    - The card label drops the "no" prefix (the funnel and statement keep `criterionLabel`).
    - Tertiary actions: "Edit · + Or another · + Later report", each with a `title`.
    - Remove becomes a `.btn-icon` ✕ with `aria-label="Remove {label}"`.
    - Chip ✕ is at least 24px.
  - The same-report toggle moves below the cards, shows only with two or more criteria or when already on, and its disabled reason is visible text.
- **Files:** `web/src/Builder.tsx`, `web/src/cohort.ts`, `web/src/styles.css`, `web/src/builder.test.tsx`, `web/src/cohort.test.ts`.
- **Acceptance:**
  - (a) No empty input without placeholder text anywhere in the builder (01).
  - (b) In the typeahead (02) the two KRAS rows read "Gene alteration · KRAS" and "RNA expression · KRAS", with no counts.
  - (c) Exclude cards read "EXCLUDE · KEAP1 or STK11 alteration" with no double negative (08).
  - (d) No "c1"/"c2" visible.
  - (e) Remove is an icon, visually distinct from Edit.
  - (f) Builder tests are updated for the renamed buttons and still pin the Then/Or availability rules.

### 6. Guided start (landing state)
- **Depends on:** 3, 5.
- **Scope:**
  - When the definition has no population filters and no criteria, the answer column shows:
    - an intro line;
    - three to five **example cohort** cards from a synthetic `EXAMPLES: Definition[]` in `cohort.ts`, with names and labels only and **no counts**;
    - the whole-population total line;
    - a small muted accrual sparkline.
  - "Use →" applies the example through the same path as a share link (`transport.apply` then `pushVersion`). Show an error if a term isn't in the vocabulary.
  - Examples use only generic, public biomarker terms.
- **Files:** `web/src/Answer.tsx` (or a new `Start.tsx`), `web/src/App.tsx`, `web/src/cohort.ts`, `web/src/styles.css`, `web/src/app.test.tsx`.
- **Acceptance:**
  - (a) The landing screenshot shows the example cards, with no number on any of them.
  - (b) Clicking one produces version n+1 with that definition, a counted answer and the share hash updated.
  - (c) A test pins that example cards render no digits other than years in their names.
  - (d) The empty Assistant and "100% of all patients" are gone from the landing page.

### 7. Panels and tabs: Feasibility, Compare, Breakdown, Pivot
- **Depends on:** 1, 2.
- **Scope:**
  - Tabs: underline style, no boxes, horizontal scroll on mobile. Keep the arrow-key handling.
  - Feasibility: anchored panel with a heading, 65ch readable text (keep the read-only textarea), primary **Copy**, focus returned to the trigger on Close. Add the "dates are shifted; the last years are partial" copy, or clamp the year, per the owner's decision (§1, 2.10).
  - Compare: "Count" → "Compare selected", and helper text when only one version exists.
  - Breakdown: purpose line plus toggle chips.
  - Pivot: purpose line, "Choose…" placeholders, selects at most 16rem wide, two or three suggested pairs (for example "Tumor type × Year") that call the existing `choose()`.
- **Files:** `web/src/App.tsx:18-32`, `web/src/Compare.tsx`, `web/src/Answer.tsx:140-206,282-293`, `web/src/styles.css`, and the tests in `app.test.tsx`, `compare.test.tsx` and `answer.test.tsx` (the "Choose rows and columns." string moves).
- **Acceptance:**
  - (a) In 04, the statement is proportional text under a heading, Copy is the only filled button, and the page below does not shift by more than the panel height.
  - (b) In 05, a single-version history shows the explanatory text, not a lone disabled button.
  - (c) The selected tab is shown by an underline, with no boxed buttons (03-*).
  - (d) The Pivot empty state shows suggested pairs.
  - (e) Every suppressed cell in the Breakdown, Pivot and Compare tables still renders "<5" with `.hatched` (existing tests pass).

**Not recommended:** a UI framework or component library. Every fix here is tokens, about a dozen CSS rules and local JSX. Nothing needs a new dependency, a web font from a CDN, or a change to the definition and operations model or the share link.