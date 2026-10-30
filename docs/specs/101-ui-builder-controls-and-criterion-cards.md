# Spec #101: UI builder controls and criterion cards

Issue #101 is item 5 of the Discover UI/UX review (`docs/reviews/2026-10-30-discover-ux.md`: §1.3,
§2.3, §2.4, §2.6, §2.7, §3.1, the §2 wireframes and §3 item 5). It depends on #97, which is merged:
that item added the design tokens and the `.btn-tertiary` and `.btn-icon` classes. This item
changes the left (builder) column of Discover, in `web/` only.

## Goal

1. Every text input in the builder has a placeholder. `Typeahead` gets a required `placeholder`
   prop.
2. Each typeahead option row starts with a plain-language kind badge, followed by the value. For
   example: "Gene alteration · KRAS" and "RNA expression · KRAS". The rows show no counts.
3. The population adders are dashed adder chips with title-case labels ("+ Tumor type").
4. The year selects read "Years [Any] – [Any]".
5. Criterion cards:
   - A coloured mode stripe on the left edge, and the mode select styled as a badge in front of
     the label.
   - The `cid` (c1, c2 …) no longer shows, but it stays in the aria labels.
   - The visible card label has no "no" prefix. The mode badge says Exclude.
   - Edit, Or and Then become tertiary text actions: "Edit · + Or another · + Later report". Each
     has a `title` that explains it.
   - Remove becomes a `.btn-icon` ✕ with `aria-label="Remove {label}"`.
6. The chip ✕ buttons are at least 24×24px.
7. The same-report toggle moves below the cards and reads "Match all criteria on the same report".
   It shows only when there are two or more criteria, any exclude or tested-negative criterion (scope changes its count), or when it is already on. When it is
   disabled, the reason shows as visible text.

## Non-goals

- **No definition, operation or share-link change.** The cards emit the same `set_mode`,
  `update_criterion`, `remove_criterion`, `add_criterion`, `set_population` and `set_scope`
  operations as today. The Or and Then availability rules (`canOr`, `canThen`, `editable`,
  `MAX_OR`, `MAX_SEQ`) don't change. `types.ts`, `transport.ts`, `api.gen.ts` and `openapi.json`
  don't change.
- **`criterionLabel` doesn't change.** The funnel, the loosen suggestions, the feasibility
  statement, Compare and the pivot axes keep the "no …" wording. Only the card heading uses the new
  `cardLabel`.
- **No ranking change.** The server's option order stays. Whether `alteration.gene` should outrank
  `expression.gene` is a server question (review 2.7) and is out of scope.
- No guided start, eyebrow headings (WHO / WITH), answer, chart, tab or panel change (items 3, 4, 6
  and 7). The "Criteria (all must match)" and "Population" headings stay as they are.
- The editors' selects (`CutSelect` "any", Vendor "any vendor", Clone "any clone", Measure
  "none") keep their option text. Each already has a non-empty first option, so none is an empty
  box.
- The pivot axis labels in `Answer.tsx` (`pivotAxes`, ``${c.id} · …``) still contain the
  criterion id. That is in the Pivot tab, not the builder, and `Answer.tsx` is outside this item's
  files (see Risks).
- No new dependency, web font, CDN, `index.html`, `vite.config.ts` or CSP change.
- **No data or output-path change.** Nothing under `src/uccc_genomics/`, `mcp/`, `dashboard/` or
  `systemd/` changes. No schema, table or column changes. The typeahead still shows only
  `{field, parent, value}` from `GET /api/options` (the `Option` schema has no count field), plus
  the static biomarker and data entries. It renders no count, so no small-cell rule is involved.
  Suppressed counts elsewhere are untouched. **`research_id` and `report_id` are not touched.**

## Design-source contradiction

`dashboard/COHORT_DISCOVERY.md` §3.3, Phase 2 paragraph, names the old controls: one "All criteria
on the same report" switch and "Then…". The PR replaces this text:

> "All criteria on the same report" switch for the definition (not a lock per card), `data` entries
> in the typeahead, a vendor select, "Then…" and the sequence card,

with:

> "Match all criteria on the same report" switch for the definition (not a lock per card; since
> #101 it sits below the cards and shows once there are two criteria or any exclude or tested-negative criterion), `data` entries in the
> typeahead, a vendor select, "+ Later report" (first called "Then…") and the sequence card,

The §3.3 "Left: builder" paragraph describes the target design (a per-card "same report" lock and
drag-to-reorder). It already differs from what is built, and the Phase 1/2 paragraphs record those
differences, so it stays as it is. README, ARCHITECTURE, PLAN and COHORT_TOOL don't name these
controls.

## Design

| File | Change |
|---|---|
| `web/src/cohort.ts` | add `KIND_LABELS`, `kindLabel`, `optionText`, `cardLabel` |
| `web/src/Builder.tsx` | Typeahead `placeholder` and option rows; adders; years; criterion card; same-report toggle |
| `web/src/styles.css` | adder chip, option badge, mode stripe and badge select, card actions, ✕ |
| `web/src/builder.test.tsx` | updated for the renamed buttons; new tests below |
| `web/src/cohort.test.ts` | tests for the new helpers |
| `web/src/styles.test.ts` | one new policy test for the builder rules |
| `dashboard/COHORT_DISCOVERY.md` | the Phase 2 sentence above |

### `cohort.ts`

Put this directly after `FIELD_LABELS` / `fieldLabel`, and keep both of those. `fieldLabel` is
still the finer description of an option ("KRAS protein change", "Specimen site type", "Tumor type
(OncoTree)"), and it becomes the row's `title`.

```ts
/** The plain-language kind badge that leads a typeahead option row. */
export const KIND_LABELS: Record<string, string> = {
  "population.oncotree": "Tumor type", "population.organ": "Organ system", "population.sex": "Sex",
  "population.age_band": "Age band", "population.vendor": "Vendor", "population.assay_class": "Assay",
  "data.has": "Data available", "biomarker.name": "Biomarker", "biomarker.call": "Biomarker",
  "alteration.gene": "Gene alteration", "alteration.aa": "Gene alteration",
  "ihc.marker": "IHC", "ihc.call": "IHC", "ihc.clone": "IHC", "expression.gene": "RNA expression",
  "specimen.site_type": "Specimen", "specimen.site": "Specimen", "actionability.evidence": "Actionability",
};

export const kindLabel = (e: Option): string => KIND_LABELS[e.field] ?? e.field;

/** An option's value as its row reads it: with its parent where the value alone is ambiguous, and plain words for codes. */
export function optionText(e: Option): string {
  const p = e.parent ? `${e.parent} ` : "";
  switch (e.field) {
    case "alteration.aa": case "biomarker.call": case "ihc.call": return `${p}${e.value}`;
    case "ihc.clone": return `${p}clone ${e.value}`;
    case "actionability.evidence": return EVIDENCE[e.value] ?? e.value;
    case "data.has": return capitalise(DATA_LABELS[e.value] ?? e.value);
    default: return e.value;
  }
}

/** A card's heading: criterionLabel without the "no" of an exclusion (the mode badge says Exclude), capitalised. */
export const cardLabel = (c: Criterion): string =>
  capitalise(criterionLabel(c.mode === "exclude" ? ({...c, mode: "include"} as Criterion) : c));
```

`KIND_LABELS` covers every field `vocabulary.py` serves (`FIELDS`) plus the two static ones
(`biomarker.name`, `data.has`), so the `?? e.field` fallback only matters for a field the server
adds later. Tested negative keeps its own wording ("KRAS tested negative") because only `exclude`
is rewritten.

Synthetic examples: `optionText({field: "alteration.aa", parent: "KRAS", value: "G12C"})` is
"KRAS G12C". With `field: "ihc.clone", parent: "PD-L1", value: "22C3"` it is "PD-L1 clone 22C3".
With `field: "data.has", value: "wts"` it is "Whole-transcriptome sequencing". With
`field: "actionability.evidence", value: "fmi_trial"` it is "FMI trial match".

### `Builder.tsx`

Imports: add `cardLabel`, `kindLabel`, `optionText` from `./cohort.ts`, and keep `fieldLabel`.

**Typeahead.** `TypeaheadProps` gets `placeholder: string`. It is required, so `tsc` fails on any
call site that leaves it out. Set `placeholder={placeholder}` on the `<input>`. Each option `<li>`
gets `title={fieldLabel(o)}`, and its body becomes:

```tsx
<span className="kind">{kindLabel(o)}</span><span aria-hidden="true"> · </span><span>{optionText(o)}</span>
```

Call sites and their placeholders (the label stays as it is unless shown):

| Call site | Label | Placeholder |
|---|---|---|
| Builder "Add criterion" | `Add criterion` | `Search genes, biomarkers, IHC, specimens… e.g. KRAS, TMB, PD-L1` |
| Population, oncotree | `Add tumor type` | `Search tumor types… e.g. NSCLC` |
| Population, organ | `Add organ` | `Search organ systems… e.g. Lung` |
| Card "+ Or another" | `Or any of` | `Search another finding… e.g. NRAS` |
| Card "+ Later report" | `Then, on a later report` | `Search a finding on the later report… e.g. liquid biopsy` |
| Sequence side | `And on the same report… (first report / later report)` | `Search a finding… e.g. KRAS` |

The examples are generic public terms; "NSCLC" and "Lung" are an OncoTree code and an organ system
from `disease_crosswalk.csv`.

**`DIM_LABELS`** becomes title case: `{oncotree: "Tumor type", organ: "Organ", sex: "Sex",
age_band: "Age", vendor: "Vendor", assay_class: "Assay"}`. Where a label sits inside a sentence it
is lower-cased: the typeahead label `` `Add ${DIM_LABELS[open].toLowerCase()}` `` and the Checks
legend `` `Limit to ${DIM_LABELS[dim].toLowerCase()}` ``. Those texts stay "Add tumor type" and
"Limit to sex".

**Adders.** Each adder button gets `className="adder"`. Its text is `+ {DIM_LABELS[d]}`, for
example "+ Tumor type". `aria-expanded` stays.

**Years.** This replaces the two labelled selects:

```tsx
<div className="years" role="group" aria-labelledby={`${yid}-years`}>
  <span id={`${yid}-years`}>Years</span>
  <select aria-label="From year" …>{/* first option */}<option value="">Any</option>…</select>
  <span aria-hidden="true">–</span>
  <select aria-label="To year" …><option value="">Any</option>…</select>
</div>
```

`yid` is `useId()` in `PopulationAdders`. The `value`/`onChange` logic (`setYears`) doesn't change.

**Population chips.** The ✕ text is "✕" (U+2715) instead of "×". The aria-labels stay
("Remove {v}", "Remove years").

**Criterion card** (`CriterionCard`):

```tsx
const label = cardLabel(c);
<article className={`criterion mode-${c.mode}`} aria-label={capitalise(criterionLabel(c))}>
  <header>
    <select className="mode" aria-label={`Mode of ${id}`} value={c.mode} onChange={…same…}>…same options…</select>
    <span aria-hidden="true"> · </span><span className="clabel">{label}</span>
  </header>
  …members / SequenceMembers as today…
  <div className="row card-actions">
    {actions}
    <button type="button" className="btn-icon remove" aria-label={`Remove ${label}`} title="Remove this criterion"
      onClick={() => onOp({op: "remove_criterion", id})}>✕</button>
  </div>
  …editor / typeaheads as today…
</article>
```

- The `<span className="cid">` is removed. The id survives in the accessible names "Mode of {id}"
  and "Remove {member} from {id}" (and "… from first/later report of {id}" in sequences). The
  article's aria-label stays `capitalise(criterionLabel(c))`, which keeps "No …" for screen readers,
  who hear the full meaning in one place.
- `actions` holds the visible tertiary buttons in this order, with a separator between each pair:

  ```tsx
  const actions = [
    editable && <button key="edit" type="button" className="btn-tertiary" aria-expanded={mode === "edit"}
      title="Change this criterion's details" onClick={…}>Edit</button>,
    canOr && <button key="or" type="button" className="btn-tertiary" aria-expanded={mode === "or"}
      disabled={c.kind === "any_of" && c.of.length >= MAX_OR}
      title="Match this or another finding (either one counts)" onClick={…}>+ Or another</button>,
    canThen && <button key="then" type="button" className="btn-tertiary" aria-expanded={mode === "then"}
      title="Also require a finding on a report later than this one" onClick={…}>+ Later report</button>,
  ].filter(Boolean).flatMap((a, i) => (i ? [<span key={`sep${i}`} className="sep" aria-hidden="true">·</span>, a] : [a]));
  ```

  The `onClick` toggles are the current ones.
- Members of an any_of and of a sequence side: their remove buttons get `className="btn-icon"`
  and the text "✕". The aria-labels and the `disabled` rule stay.

**Same-report toggle** (`Builder`). It moves out of its place above the cards to after the
Add-criterion typeahead (the review's wireframe):

```tsx
const sid = useId();
const showSameReport = d.criteria.length >= 2 || d.scope === "report";
…
{d.criteria.map(…cards…)}
<Typeahead label="Add criterion" placeholder="…" … />
{showSameReport && (
  <div className="same-report">
    <label>
      <input type="checkbox" checked={d.scope === "report"} disabled={sameReportBlocked}
        aria-describedby={sameReportBlocked ? `${sid}-why` : undefined}
        onChange={…same…} /> Match all criteria on the same report
    </label>
    {sameReportBlocked && <p id={`${sid}-why`} className="hint">A sequence, testing by both vendors or serial reports spans several reports, so it cannot be matched on one report.</p>}
  </div>
)}
```

The `title` attribute on the label is removed, because the reason is now visible text.
`sameReportBlocked` stays as it is, so it is false at report scope. A definition already at report
scope can always be switched back.

### `styles.css`

Change or add these rules in the `/* builder */` block. Use only defined tokens (the
`styles.test.ts` rules apply: no raw hex, and every `var()` must be defined).

```css
.adder { border: 1px dashed var(--line); border-radius: 999px; background: transparent; }
.adder[aria-expanded="true"] { border-style: solid; background: var(--surface-2); }
.criterion { border-left-width: 4px; }
.criterion.mode-include { border-left-color: var(--high); }
.criterion.mode-exclude { border-left-color: var(--low); }
.criterion.mode-tested_negative { border-left-color: var(--muted); }
.criterion header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s1); margin-bottom: .3rem; }
.criterion .mode {
  border-radius: 999px; font-size: var(--fs-xs); line-height: var(--lh-xs); font-weight: 600;
  text-transform: uppercase; letter-spacing: .06em; padding-inline: var(--s2);
}
.criterion.mode-include .mode { color: var(--high); background: var(--high-bg); }
.criterion.mode-exclude .mode { color: var(--low); background: var(--low-bg); }
.criterion.mode-tested_negative .mode { color: var(--fg); background: var(--surface-2); }
.card-actions { gap: var(--s1); }
.card-actions .sep { color: var(--muted); }
.card-actions .remove { margin-left: auto; }
.typeahead li { justify-content: flex-start; gap: 0; }
.typeahead .kind {
  font-size: var(--fs-xs); line-height: var(--lh-xs); font-weight: 600; white-space: nowrap;
  padding: 2px var(--s2); border-radius: 999px; background: var(--surface-2); color: var(--muted); align-self: center;
}
.typeahead li[aria-selected="true"] .kind { background: transparent; color: inherit; }
.same-report { margin: .4rem 0; }
.same-report .hint { margin-left: 1.5rem; }
```

- Remove `.cid`, `.typeahead .field` and `.criterion header select { margin-left: .5rem; }`.
  Nothing renders them any more.
- In the existing `.typeahead li` rule, drop `justify-content: space-between` and the `.75rem`
  gap, or override them as above. The badge leads the row and the value follows it.
- The badge select keeps the base 36px `min-height` (44px on coarse pointers). It does not
  override it.
- `.chip button` keeps `min-height: 24px; min-width: 24px` from #97. The coarse-pointer rule
  already raises it to 44px. The ✕ glyph change needs no CSS.
- The contrast pairs these rules add are already pinned at 4.5:1 in `styles.test.ts`:
  `--high`/`--high-bg`, `--low`/`--low-bg`, `--muted`/`--surface-2` and `--accent`/`--bg`.
  `--fg` on `--surface-2` is added to the pair list, for the tested-negative badge.

## Acceptance criteria

- [ ] (a) The builder has no text input without a placeholder. `placeholder` is a required
      `Typeahead` prop (`bun run typecheck` fails without it). A static render of the Builder with
      an alteration and a sequence card has every non-checkbox `<input` carrying a non-empty
      `placeholder` (builder test). The Add-criterion placeholder is the §1.3 text.
- [ ] (b) Option rows lead with the kind: `kindLabel` gives "Gene alteration" for
      `alteration.gene` and "RNA expression" for `expression.gene`, and `optionText` gives "KRAS"
      for both. The row markup is badge, " · ", text. Rows render nothing from the `Option` beyond
      `field`, `parent` and `value`, so there are no counts (cohort tests). The orchestrator checks
      screenshot 02.
- [ ] (c) An exclude card for genes KEAP1 and STK11 renders the mode select (with Exclude
      selected) before `<span class="clabel">KEAP1 or STK11 alteration</span>`, and no visible
      ">No KEAP1" text. `criterionLabel` still returns "no KEAP1 or STK11 alteration" (builder and
      cohort tests).
- [ ] (d) No `c1`/`c2` text node in the builder markup, while `aria-label="Mode of c1"` is still
      present (builder test).
- [ ] (e) Remove is `<button … class="btn-icon remove" aria-label="Remove KRAS alteration" …>✕</button>`,
      and Edit is a `btn-tertiary`. There is no `>Remove</button>` (builder test).
- [ ] (f) The builder tests use the new names (`+ Or another`, `+ Later report`) and still pin the
      current rules. "+ Later report" is offered for an include finding. It is not offered for an
      exclusion, a sequence, report scope or per-patient data. "+ Or another" is not offered for
      data.
- [ ] Adders are `class="adder"` buttons reading "+ Tumor type" … "+ Assay". The years row reads
      "Years", with two selects whose empty option is "Any", and no "All years", "From" or "To"
      label text (builder test).
- [ ] The same-report toggle is absent with zero or one criterion at patient scope. It is present
      after the last card with two criteria, and present and checked at report scope even with
      none. When it is blocked, the checkbox is disabled and `aria-describedby` points at a
      visible `.hint` that contains "cannot be matched on one report" (builder test).
- [ ] `styles.css` has `.adder` dashed, mode stripes using `--high`/`--low`, and `.chip button`
      at least 24px. It has no `.cid` or `.typeahead .field` rule (styles test). The existing
      styles tests pass.
- [ ] `COHORT_DISCOVERY.md` Phase 2 carries the replacement sentence.
- [ ] `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` passes.
      `uv run pytest -q` and the dashboard check are n/a (`web/` only, no API model change). Report
      them as n/a.

## Test plan

```bash
cd web && bun install --frozen-lockfile && bun run typecheck && bun test
```

All tests are static renders (`renderToStaticMarkup`) or pure-function tests over synthetic
definitions and options, as today. No DOM library may be added. Nothing reads `$DATA`.

**`cohort.test.ts`** (add `KIND_LABELS`, `cardLabel`, `kindLabel`, `optionText` to the import):

1. `kindLabel` / `optionText`: `opt("alteration.gene", "KRAS")` gives "Gene alteration" / "KRAS".
   `opt("expression.gene", "KRAS")` gives "RNA expression" / "KRAS". `opt("alteration.aa",
   "G12C", "KRAS")` gives "Gene alteration" / "KRAS G12C". `opt("biomarker.call", "high", "MSI")`
   gives "Biomarker" / "MSI high". `opt("ihc.clone", "22C3", "PD-L1")` gives "IHC" / "PD-L1 clone
   22C3". `opt("population.oncotree", "NSCLC")` gives "Tumor type" / "NSCLC". `opt("data.has",
   "wts")` gives "Data available" / "Whole-transcriptome sequencing".
   `opt("actionability.evidence", "fmi_trial")` gives "Actionability" / "FMI trial match".
   `opt("x.unknown", "v")` gives "x.unknown" / "v".
2. `KIND_LABELS` has a key for every field in `vocabulary.py`'s `FIELDS` and for
   `biomarker.name` and `data.has`. List the 18 field names literally in the test.
3. `cardLabel`: `alt({mode: "exclude", gene: ["KEAP1", "STK11"]})` gives "KEAP1 or STK11
   alteration", while `criterionLabel` of the same gives "no KEAP1 or STK11 alteration".
   `alt({mode: "tested_negative"})` gives "KRAS tested negative". An exclude `data` `both_vendors`
   gives "Testing by both Caris and FMI". An include alteration with `class: ["mutation"]` gives
   "KRAS mutation".

**`builder.test.tsx`**:

- Update the `options()` helper regex to `<select[^>]*aria-label="Mode of ${id}"[^>]*>`, because
  `class="mode"` now renders before `aria-label`.
- Rename the "Then…" tests to match `>+ Later report</button>`, and the "Or…" test to match
  `>+ Or another</button>`. Keep each assertion's polarity and fixture. Match `>+ Later report<`,
  not bare "Later report": the sequence card's `<h4>Later report</h4>` contains that text. The
  exclusion test becomes `not.toContain(">+ Later report</button>")`.
- Same-report tests, replacing the two current ones:
  - `render(EMPTY)` and `render({...EMPTY, criteria: [alt]})` do not contain "same report".
  - `render({...EMPTY, criteria: [alt, ihc]})` contains "Match all criteria on the same report"
    without `checked=""` on that input, and its index is after the last `</article>`.
  - `render({...EMPTY, scope: "report"})` matches `/checked=""[^>]*\/> Match all criteria on the
    same report/`.
  - With `[alt, sequence]`, the checkbox matches `<input type="checkbox" disabled=""[^>]*aria-describedby="([^"]+)"`.
    The markup contains `<p id="{that id}" class="hint">` with "cannot be matched on one report",
    and no `title=` on the label. With `[alt, ihc]` it is not disabled and has no
    `aria-describedby`.
- New tests:
  - **Placeholders:** in `render({...EMPTY, criteria: [alt, sequence]})`, every
    `/<input(?![^>]*type="checkbox")[^>]*>/` match (expect at least 3: Add criterion and the two
    sequence sides) has `placeholder="[^"]+"`. The markup contains
    `placeholder="Search genes, biomarkers, IHC, specimens… e.g. KRAS, TMB, PD-L1"`.
  - **Adders and years:** `render(EMPTY)` has six `class="adder"` buttons, `>+ Tumor type</button>`
    and `>+ Assay</button>`, a `>Years</span>`, exactly two `<option value="">Any</option>`, and no
    "All years", `>From` or `>To`.
  - **Exclude card:** a criterion `{...alt, id: "c1", mode: "exclude", gene: ["KEAP1", "STK11"]}`
    has `<option value="exclude" selected="">` and `<span class="clabel">KEAP1 or STK11
    alteration</span>`. The index of `aria-label="Mode of c1"` is before the `clabel` index, the
    markup does not contain `>No KEAP1`, and it has `class="criterion mode-exclude"`.
  - **No visible cid:** `render({...EMPTY, criteria: [alt, ihc]})` does not match `/>c\d+</` and
    contains `aria-label="Mode of c1"` and `aria-label="Mode of c2"`.
  - **Remove is an icon:** `render({...EMPTY, criteria: [alt]})` contains
    `class="btn-icon remove" aria-label="Remove KRAS alteration"` and `>✕</button>`, Edit carries
    `class="btn-tertiary"`, and there is no `>Remove</button>`. The tertiary actions are separated:
    the markup contains `>Edit</button><span class="sep" aria-hidden="true">·</span>`.
- The existing sequence-member aria-label tests ("Remove tissue testing from first report of c4"
  …) and the data-card aria-label test stay as they are and still pass.

**`styles.test.ts`**: add `["--fg", "--surface-2"]` to the contrast pair list. Add one test:
`rule(".adder")` contains `dashed`, `rule(".criterion.mode-include")` contains `var(--high)`,
`rule(".criterion.mode-exclude")` contains `var(--low)`, `rule(".chip button")` contains
`min-height: 24px` and `min-width: 24px`, and the CSS contains neither `.cid` nor
`.typeahead .field`.

## Risks

- **Pivot axes still show the id.** `pivotAxes` labels read "c1 · KRAS alteration · gene" in the
  Pivot tab. Acceptance (d) is about the builder (screenshots 01 and 08). If the orchestrator reads
  (d) page-wide, that is an `Answer.tsx`/`cohort.ts` follow-up for item 7 (#103), which reworks
  the Pivot panel. It is not done here, because `pivotAxes` values are `c1.key`-style ids that the
  label has to disambiguate.
- **Uppercase select text.** `text-transform: uppercase` on a `<select>` applies to the closed
  control in Chromium, Firefox and Safari. The open option list is native and may show
  "Exclude". Both are fine. The stripe colour carries the mode as well.
- **Remove labels can collide.** Two cards with the same label (for example an include and an
  exclude of the same gene) both get "Remove KRAS alteration". The article's aria-label ("KRAS
  alteration" vs "No KRAS alteration") tells them apart in a screen reader's landmark list. The
  issue asks for `Remove {label}` without the id, so the id isn't added.
- **Hidden toggle state.** The same-report toggle hides at one criterion. If a user is at report
  scope and removes criteria down to one, the toggle stays visible (`scope === "report"`), so the
  state is never hidden while it is on.
- **`useId` in tests.** The hint id is generated, so tests read it from `aria-describedby` and
  never hard-code it.
