# Spec #71: follow-ups from the #38 review

Issue #71 lists the minor/nit findings from the #38 review (cohort phase 2) that were not fixed
before merge, plus findings folded in from #69. This spec fixes all of them in one PR, with two
exceptions. **security-r0-3** is already fixed on `main` (see Goal 7), so it is only checked and
closed. **security-r0-1** (a `sequence` against the AND of its members) stays with the #72 decision,
as the issue says.

The issue says "do not change suppression rules here". So for the two privacy findings that offer
"document it, or extend `neighbours()`" (**code-r0-3**, **security-r0-2**), this spec takes the
documentation option. `neighbours()`, `_neighbour_count()`, `MAX_NEIGHBOURS` and every rule in
`suppress.py` stay as they are. #72 is where the neighbour set may grow.

## Goal

1. **code-r0-2**: the `dashboard/COHORT_DISCOVERY.md` §3.1 kinds table is one table again. The
   "Every leaf kind…" sentence moves below it and says the right thing.
2. **code-r0-3**: the two-query exposures that the neighbour check does not cover are named
   wherever accepted risks are listed: a criterion's own `vendor` (none against one vendor), and
   patient scope against report scope when that pair is more than one edit apart. The claim
   "closes two-query attacks one edit away" is softened.
3. **code-r0-4**: `update_criterion` that turns a pivot-axis criterion into one that cannot be an
   axis clears the pivot (as `remove_criterion` and `set_mode` already do), so "Then…" on that card
   no longer ends in a 400.
4. **code-r0-5**: `test_loosen_withheld_with_neighbours` asserts something for a suppressed cohort.
5. **code-r0-6**: `test_compile_phase2_binds_values` no longer strips `'caris'` / `'fmi'` from the
   SQL, and pins a `$…_vendor` parameter for every criterion and sequence member with a vendor.
6. **security-r0-2**: "two or more values taken out of one population field" is named as an
   accepted risk in the same places as Goal 2.
7. **security-r0-3**: already covered. `feasibility()` in `web/src/cohort.ts` writes a null count as
   "a suppressed number" (never "fewer than 5"), and its closing sentence says "counts under 5, and
   counts that would let one be worked out by subtraction, are not shown". The `cohort.test.ts`
   case "a suppressed count claims no size and has no number" pins both. No change; the PR says it
   closes this item.
8. **ux-r0-2**: the Patients card never shows "in <5 reports" for a hidden `reports`.
9. **ux-r0-3**: the Feasibility panel never shows a blank textarea, never copies an empty
   statement, resets "Copied" when the statement changes, and can always be closed.
10. **ux-r0-5**: the Compare table explains its blank year cells.
11. **ux-r0-6**: the alteration editor of a `tested_negative` criterion offers only what Save
    accepts.
12. **ux-r0-7**: `CountResult.loosen_offered` has a schema description; `INSTRUCTIONS` and the
    `count` docstring mention it and name every neighbour.
13. **ux-r1-3**: `DATA_LABELS` are noun phrases that read well after "no" and "then later".
14. **ux-r2-2**: the "All criteria on the same report" switch, "Then…" and the add-criterion
    typeahead offer only what report scope accepts.
15. **code-r3-1**: `INSTRUCTIONS` and the `count` docstring say which reports `reports` counts on
    this branch (include criteria only; every criterion on one report at report scope).

## Non-goals

- **No change to suppression.** `neighbours()`, `_neighbour_count()`, `_scope_swap()`,
  `MAX_NEIGHBOURS`, `suppress_count`, `suppress_pivot`, `floor` and the loosen rules are not
  edited. No count that is shown today becomes hidden, or the reverse. The only code change in the
  cohort module is the pivot clearing in `apply` (Goal 3) and a `Field` description (Goal 12).
- **security-r0-1** (sequence against the AND of its members) is not touched; #72 decides it.
- No change to `deid.py`, the de-id file, `sql/*.sql`, `compile.py`, `cohort_api.py`, `server.py`,
  `saved.py`, `authen.py`, the dashboard or `systemd/`. No data change, so no vendor source field
  is involved and **`research_id` and `report_id` stability is not affected**.
- No new output path, endpoint, tool or export.
- The `Count` component keeps rendering null as `<5` with the `SUPPRESSED` title everywhere except
  the Patients card's reports line (Goal 8). Compare's `<5` cells are already explained by the
  existing `SUPPRESSED` legend ("…or hidden so that a small count cannot be worked out by
  subtraction"), which covers the Compare half of ux-r0-2; Goal 10 adds only the blank-cell line.
- Labels other than `DATA_LABELS` keep their case. `criterionLabel` stays lower-case-first for
  `data` and `specimen` criteria (as `specimen` already is); only the Builder's card heading and
  member list items capitalise the first letter (Goal 13).
- No new dependency (Python or web).

## Design

Files that change:

| File | Change |
|---|---|
| `dashboard/COHORT_DISCOVERY.md` | §3.1 sentence moved and reworded; §3.6 rows (Goals 2, 6) |
| `docs/specs/38-cohort-phase-2-exclusion-report-scope.md` | Non-goals, Risks, `app.py` bullet, `DATA_LABELS` block (Goals 2, 6, 12, 13, 15) |
| `mcp/src/uccc_genomics_mcp/cohort/definition.py` | `_can_be_axis`, `_axis_uses`; `apply` clears the pivot on `update_criterion` |
| `mcp/src/uccc_genomics_mcp/cohort/suppress.py` | module docstring (Goals 2, 6); `loosen_offered` `Field` description |
| `mcp/src/uccc_genomics_mcp/app.py` | `INSTRUCTIONS`, `count` docstring |
| `web/openapi.json`, `web/src/api.gen.ts` | regenerated with `bun run gen` (the new description) |
| `web/src/cohort.ts` | `DATA_LABELS`, `capitalise`, `forScope` |
| `web/src/Builder.tsx` | headings, `AlterationEditor`, scope switch, `canThen`, add-criterion search |
| `web/src/Answer.tsx` | Patients card reports line |
| `web/src/App.tsx` | `FeasibilityPanel`, toggle, Copy, `statementCopied` reset |
| `web/src/Compare.tsx` | blank-cell legend |
| tests | `tests/test_cohort.py`, `tests/test_cohort_phase2.py`, `tests/test_app.py`, `web/src/cohort.test.ts`, `web/src/builder.test.tsx`, `web/src/answer.test.tsx`, `web/src/compare.test.tsx`, new `web/src/app.test.tsx` |

### 1. `dashboard/COHORT_DISCOVERY.md` §3.1 (code-r0-2)

Delete the line "Every leaf kind (`alteration` to `data`, not `any_of` or `sequence`) also takes
`vendor` (`caris`, `fmi` or null) and `mode`." from between the `data` and `actionability` rows,
so the table runs unbroken from `alteration` to `sequence`. After the table, with one blank line
before it, add:

> Every leaf kind (all but `any_of` and `sequence`) takes `vendor` (`caris`, `fmi` or null). Every
> criterion takes `mode`, except `sequence`, which is include-only. Only `alteration` can be
> `tested_negative`.

### 2. Accepted risks (code-r0-3, security-r0-2)

The same three items go into four places. Wording (adapt only the sentence frame to each place):

- **A criterion's own vendor.** `vendor: null` on a criterion is an OR of Caris and FMI, like an
  OR list. A criterion without a vendor against the same criterion with `vendor: "caris"` is one
  `update_criterion` apart, and the difference is the patients whose finding is only on FMI
  reports. It is accepted with OR lists inside a criterion.
- **Two or more values taken out of one population field.** The union rule takes out one value at
  a time. A patient whose reports carry two listed values (two OncoTree codes, or two age bands)
  stays in when either one alone is taken out, so `[A, B, C]` against `[A]` can differ by 1–4
  while every one-value neighbour differs by 0. It takes two queries and one `set_population`.
- **Patient scope against report scope beyond one edit.** The patient-scope twin of a report-scope
  cohort is a neighbour. The pair combined with another edit (for example the scope switch and a
  criterion's vendor together) is two edits away and is not checked.

Places:

1. **`docs/specs/38-cohort-phase-2-exclusion-report-scope.md`**
   - Non-goals, the "union rule does not cover OR lists" bullet: append "or a criterion's own
     `vendor` (none against one vendor), and the union rule takes out one value at a time, not two
     or more from one field".
   - Risks, first bullet: replace "The neighbour check closes two-query attacks one edit away." with
     "The neighbour check closes the two-query attacks one edit away that `neighbours()` lists
     (§3.6 names them). These stay open and are accepted…" and add the three items above as
     sub-bullets after "OR lists inside a criterion (decision 1's scope)".
2. **`dashboard/COHORT_DISCOVERY.md` §3.6**
   - Multi-select population row, Control cell: move the report-scope sentences ("So is a
     report-scope cohort … a report without it).") out to a new row (below). Extend the closing
     accepted list: "…as are OR lists inside a criterion (several genes, protein changes or
     `any_of` members), a criterion's own `vendor` (none against one vendor: the difference is the
     patients whose finding is only on the other vendor's reports), and two or more values taken
     out of one population field (a patient with two listed values stays in when either alone is
     taken out), as `COHORT_TOOL.md` does for differencing today."
   - New row directly after the multi-select row:
     `| Report scope | A report-scope cohort is nested in the same cohort at patient scope; both shown give the patients whose criteria match only on different reports. | The neighbour check (#38): a report-scope cohort with two or more criteria, or with any exclusion, has its patient-scope twin as a neighbour (for one exclusion, the difference is those with B on one report and a report without it). One include criterion counts the same at both scopes. The scope switch combined with another edit is two edits away and accepted under the audit log. |`
3. **`suppress.py` module docstring**: replace the "Not covered, and accepted…" sentence with
   "Not covered, and accepted under the audit log (spec rule 3, COHORT_DISCOVERY.md §3.6): OR lists
   inside a criterion, a criterion's own vendor (none against one vendor), two or more values taken
   out of one population field, the scope switch combined with another edit, differencing that
   combines three or more queries, and that breakdown cell against its denominator."

### 3. `definition.py`: pivot clearing on `update_criterion` (code-r0-4)

Add, next to `_has_specimen`:

```python
def _can_be_axis(c) -> bool:
    """The rule `_check_pivot` enforces on a criterion axis, as a predicate."""
    return c.mode not in NEGATED and c.kind not in ("data", "sequence") and not _has_specimen(c)


def _axis_uses(pivot: dict | None, cid: str) -> bool:
    return bool(pivot) and any(a.startswith(f"{cid}.") for a in (pivot["rows"], pivot["cols"]))
```

In `apply`:

- `UpdateCriterion`: after `criteria[position[o.id]] = …`, add
  `if _axis_uses(data["pivot"], o.id) and not _can_be_axis(o.criterion): data["pivot"] = None`.
  An update that keeps the criterion a valid axis keeps the pivot.
- `RemoveCriterion` and `SetMode`: replace their inline `pivot and any(a.startswith(...))`
  expressions with `_axis_uses(data["pivot"], o.id)`. Same behaviour.

`_check_pivot` keeps its specific error messages and is not rewritten. The web needs no change:
"Then…" sends `update_criterion` to `POST /api/apply`, which runs this `apply`.

### 4. `suppress.py`: `loosen_offered` description (ux-r0-7)

`from pydantic import BaseModel, Field`, and:

```python
loosen_offered: bool = Field(True, description=(
    "False when the definition has neighbours (exclusions, multi-value population fields, a year "
    "range or report scope): loosen suggestions are then not computed, so an empty loosen means "
    "'not offered', not 'none would help'."))
```

The default stays `True` (snapshots stored before #38 still validate). Regenerate with
`cd web && bun run gen`; the only diff in `web/openapi.json` is the `description` key on
`loosen_offered`, and `web/src/api.gen.ts` gains the matching doc comment.

### 5. `app.py`: `INSTRUCTIONS` and the `count` docstring (ux-r0-7, code-r3-1)

Keep the fragments wrapped at about 110 characters (spec #65).

- In `INSTRUCTIONS`, replace "reports counts the cohort patients' in-population reports (Caris
  and FMI) that match at least one criterion, or every population report when there are no
  criteria; it is not a patient count." with:
  "reports counts the cohort patients' in-population reports (Caris and FMI) that match at least
  one include criterion (an exclude, tested_negative, both_vendors or serial criterion never makes
  a report count), or all of them when no criterion can; with scope 'report', the reports on which
  every criterion holds; it is not a patient count."
- In `INSTRUCTIONS`, replace "A count can also be null because it differs by 1-4 from the same
  cohort without an exclusion or one population value (so a small group cannot be worked out by
  subtraction)." with:
  "A count can also be null because it differs by 1-4 from the same cohort one edit away: without
  an exclusion, with a tested_negative criterion as a plain exclude, without one listed population
  value or one end year of a year range, or at patient scope instead of report scope (the result's
  notes say so). Then loosen_offered is false: loosen suggestions were not computed, so an empty
  loosen does not mean that no single criterion would help."
- `count` docstring: replace "and, for a cohort too small to show, which criterion to loosen." with
  "and, for a cohort too small to show, which criterion to loosen (only when loosen_offered is true;
  when it is false no suggestion was computed)." Replace its `reports` sentence with the same
  wording as `INSTRUCTIONS` above.
- `docs/specs/38-…md` `### app.py` bullet: replace the quoted `INSTRUCTIONS` sentence with the new
  neighbour sentence, and add one bullet: "`count` docstring and `INSTRUCTIONS` say what
  `loosen_offered` false means, and which reports `reports` counts (#71)."

### 6. `web/src/cohort.ts` (ux-r1-3, ux-r2-2)

```ts
export const DATA_LABELS: Record<string, string> = {
  wts: "whole-transcriptome sequencing", liquid: "liquid biopsy", tissue: "tissue testing",
  both_vendors: "testing by both Caris and FMI", serial: "serial reports (two or more)",
};

/** s with its first letter upper-cased, for a label that stands alone (a card heading). */
export const capitalise = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** Vocabulary entries a definition of this scope can add: report scope drops per-patient data. */
export function forScope(entries: Option[], scope: Definition["scope"]): Option[] {
  return scope === "report" ? entries.filter((e) => e.field !== "data.has" || REPORT_DATA.includes(e.value)) : entries;
}
```

`criterionLabel` and `baseLabel` are unchanged; they now give, for example, "liquid biopsy",
"no testing by both Caris and FMI", "tissue testing, then later liquid biopsy (Caris) and KRAS
mutation". `dataEntries` keeps matching on the label text ("liquid", "transcriptome", "two" still
match). `docs/specs/38-…md`'s `DATA_LABELS` block changes to these values.

### 7. `web/src/Builder.tsx`

- **Headings (ux-r1-3).** Import `capitalise`. `CriterionCard`'s `<article aria-label>` and
  `.clabel` text use `capitalise(criterionLabel(c))`. The member `<li>` texts in the `any_of`
  list and in `SequenceMembers` use `capitalise(criterionLabel(m))`. The Remove buttons'
  `aria-label`s keep `criterionLabel(m)` (mid-sentence).
- **`AlterationEditor` (ux-r0-6).** Export it. When `d.mode === "tested_negative"`:
  - the class `Checks` gets `values={["mutation"]}` (none still means any class);
  - the protein-change `Checks` is not rendered;
  - a `<p className="hint">Tested negative is per gene: it takes no protein change and no
    copy-number or fusion class.</p>` follows the class checks.
  Other modes render as today.
- **Scope switch (ux-r2-2).** Add, at module level,
  `const spansReports = (c: Criterion) => c.kind === "sequence" || (c.kind === "data" && !REPORT_DATA.includes(c.has));`
  The checkbox gets `disabled={d.scope !== "report" && d.criteria.some(spansReports)}` and, when
  disabled, `title="A sequence, testing by both vendors or serial reports spans several reports, so
  it cannot be matched on one report"` (on the `<label>`, so it shows on hover of the text too).
  Unchecking stays possible whenever the scope is `report`.
- **`canThen` (ux-r2-2).** `CriterionCard` gets a `scope: Definition["scope"]` prop (passed from
  `Builder` as `d.scope`), and `canThen` gains `&& scope !== "report"`.
- **Add-criterion typeahead (ux-r2-2).** `search={(q) => searchAll(transport, q).then((r) => forScope(r, d.scope))}`.
  The Or… typeahead already drops `data.has`; the Then… typeahead is not offered at report scope.

### 8. `web/src/Answer.tsx`: Patients card (ux-r0-2)

In `Cards`, the sub line becomes:

```tsx
<p className="sub">{r.reports == null
  ? <span className="suppressed" title={SUPPRESSED}>reports not shown</span>
  : <>in <Count n={r.reports} minCell={r.min_cell} /> reports</>}</p>
```

This applies whether or not `patients` is shown: a hidden `reports` says nothing about its size.

### 9. `web/src/App.tsx`: Feasibility panel (ux-r0-3)

Add and export, in `App.tsx`:

```tsx
export function FeasibilityPanel({statement, copied, onCopy, onClose, textareaRef}: {
  statement: string; copied: boolean; onCopy: () => void; onClose: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
})
```

It renders `<section aria-label="Feasibility statement" className="panel">` with:

- when `statement === ""`: `<p role="status">Recounting… the statement updates when the count is
  current.</p>` instead of the textarea; otherwise today's read-only textarea;
- a row with `<button type="button" disabled={statement === ""} onClick={onCopy}>Copy</button>`,
  `{copied && <span role="status">Copied</span>}` and
  `<button type="button" onClick={onClose}>Close</button>`.

In `App`:

- The panel JSX is replaced by `<FeasibilityPanel statement={statement} copied={statementCopied}
  onCopy={copyStatement} onClose={() => setPanel(null)} textareaRef={statementRef} />`.
- `useEffect(() => setStatementCopied(false), [statement]);`
- The top-bar toggle: `disabled={panel !== "feasibility" && (!answer || stale)}`, so an open panel
  can always be closed from it.
- `copyStatement` returns early when `statement === ""`.

`statement` is `""` exactly when there is no answer or it is stale (unchanged expression). A failed
recount leaves the "Recounting…" line in the panel; the Answer column's alert with Retry says it
failed.

### 10. `web/src/Compare.tsx`: blank-cell legend (ux-r0-5)

In `CompareTable`:

```ts
const yearsShown = (c: CompareColumn) => c.result != null && c.result.patients != null;
const anyBlank = years.some((y) => columns.some((c) => yearsShown(c) && !c.result!.by_year.some((x) => x.year === y)));
```

A column whose `patients` is null has `by_year == []` from the server (`suppress.py`), so its year
cells render as `<Count n={null}>` (`<5`, with the existing legend), never blank, and it does not
count towards `anyBlank`: a hidden count is not "no patients". After the existing `<5` legend, `{anyBlank && <p className="legend">Blank: no patients that
year for that version.</p>}`. The existing `<5` legend text (`SUPPRESSED`) is unchanged.

## Acceptance criteria

- [ ] `COHORT_DISCOVERY.md` §3.1: the kinds table has no non-table line between its header and the
      `sequence` row; the sentence below it says `vendor` is on every kind but `any_of` and
      `sequence`, `mode` on every criterion but `sequence`, and `tested_negative` only on
      `alteration`.
- [ ] Spec 38 (Non-goals, Risks), §3.6 and the `suppress.py` docstring name a criterion's own
      vendor, two or more values out of one population field, and the scope switch combined with
      another edit as accepted. §3.6 has a Report scope row. Spec 38 Risks no longer says "closes
      two-query attacks one edit away" unqualified.
- [ ] `apply(d, update_criterion)` turning a pivot-axis criterion into a `sequence`, `data`,
      specimen, `exclude` or `tested_negative` criterion returns a definition with `pivot is None`
      and raises nothing; an update that keeps it a valid axis keeps the pivot.
- [ ] `neighbours()`, `_neighbour_count()` and every `suppress.py` rule are byte-identical to
      `main` apart from the docstring and the `Field` description (`git diff` shows it).
- [ ] `test_loosen_withheld_with_neighbours` asserts `r.loosen == [] and r.loosen_offered is False`
      for the PAAD cohort, with no `or`.
- [ ] `test_compile_phase2_binds_values` has no `.replace(` and checks the exact set of
      `$…_vendor` names in each SQL.
- [ ] `CountResult`'s OpenAPI schema has a `description` on `loosen_offered` containing
      "not offered"; `web/openapi.json` and `api.gen.ts` match `bun run gen` (`bun run typecheck`
      and `test_app.py`'s committed-schema test pass).
- [ ] `INSTRUCTIONS` names all five neighbour kinds and `loosen_offered`; it and the `count`
      docstring say only include criteria make a report count, and what report scope counts.
- [ ] The Patients card shows "reports not shown" (never "<5 reports") when `reports` is null.
- [ ] The Feasibility panel with an empty statement shows the "Recounting…" line, no textarea, a
      disabled Copy and a Close button; the top-bar toggle is enabled while the panel is open.
- [ ] Compare shows the blank-cell legend when a year cell is blank and not otherwise.
- [ ] A `tested_negative` alteration editor offers only the `mutation` class, no protein change,
      and the hint.
- [ ] `DATA_LABELS` are the five phrases above; card headings capitalise them; no rendered label
      contains "no Has", "no Tested" or "then later Has".
- [ ] With a `sequence`, `both_vendors` or `serial` criterion at patient scope the same-report box
      is disabled with the title; at report scope no card offers "Then…" and `forScope` drops
      `both_vendors`/`serial` entries.
- [ ] `uv run pytest -q`, `cd web && bun install --frozen-lockfile && bun run typecheck && bun test`
      pass. Dashboard check: n/a (nothing under `dashboard/` but a markdown file).

## Test plan

All Python tests use the synthetic mart the existing cohort tests build in a temp `DATA` dir
(`tests/test_cohort.py` / `test_cohort_phase2.py` fixtures); none reads `$DATA/raw/` or the PHI
file. Web tests are static renders and pure functions with synthetic results.

Python:

- `tests/test_cohort_phase2.py`
  - `test_loosen_withheld_with_neighbours`: first assertion becomes
    `assert r.loosen == [] and r.loosen_offered is False`.
  - `test_compile_phase2_binds_values`: drop both `.replace` calls (the value loop checks
    `value not in sql`). Replace `assert "$k0_vendor" in sql and "$k1_vendor" in sql` with
    `assert set(re.findall(r"\$k\w*_vendor", sql)) == expected`, where `expected` is built from the
    **parsed** `d` (Definition reorders sequence members, so the test must not hard-code member
    indices): `{f"$k{i}_vendor"}` for each top-level criterion with a vendor, and
    `{f"$k{i}{s}{j}_vendor"}` (`s` = `f` for `first`, `t` for `then`) for each sequence member
    with a vendor. On today's code that is `k0`–`k3` plus `k4f0` and `k4t0` at patient scope and
    `k0`–`k3` at report scope (checked against `compile.py` while writing this spec). Add
    `import re` (the file does not import it today).
  - New `test_update_criterion_clears_a_pivot_it_cannot_keep`: `d` with `c1` = KRAS alteration,
    `c2` = ER ihc, `pivot={"rows": "c1.key", "cols": "year"}`. For each replacement of `c1`
    (`{"kind": "sequence", "first": [<c1 without id>], "then": [{"kind": "data", "has": "liquid"}]}`,
    `{"kind": "data", "has": "wts"}`, `{"kind": "specimen", "site_type": ["metastatic"]}`, KRAS with
    `mode: "exclude"`, KRAS with `mode: "tested_negative"`), `apply(d, {"op": "update_criterion",
    "id": "c1", "criterion": …}).pivot is None`. Updating `c1` to NRAS alteration keeps
    `pivot == d.pivot`; updating `c2` to a `data` criterion keeps it too (the pivot does not use
    `c2`).
- `tests/test_cohort.py::test_operations`: unchanged and still passing (pins that the
  `remove_criterion` / `set_mode` refactor keeps behaviour).
- `tests/test_app.py`
  - `test_instructions_say_how_cells_overlap` keeps passing unchanged.
  - New `test_instructions_name_neighbours_and_loosen_offered`: the whitespace-normalised
    `INSTRUCTIONS` contains "with a tested_negative criterion as a plain exclude", "one end year",
    "at patient scope instead of report scope", "loosen_offered is false" and "at least one include
    criterion"; it no longer contains "match at least one criterion,".
  - New `test_loosen_offered_is_described`: `app.app().openapi()["components"]["schemas"]
    ["CountResult"]["properties"]["loosen_offered"]["description"]` contains "not offered".
  - The existing committed-`openapi.json` test passes after `bun run gen`.

Web (`bun test`):

- `cohort.test.ts`: update the data/sequence expectations to "liquid biopsy", "no testing by both
  Caris and FMI", "tissue testing, then later liquid biopsy (Caris) and KRAS mutation". Add
  `capitalise("liquid biopsy") === "Liquid biopsy"` and `capitalise("") === ""`. Add `forScope`:
  at `"report"` the `both_vendors` and `serial` `data.has` entries are dropped and `wts`, `liquid`,
  `tissue` and a gene entry kept; at `"patient"` the input comes back unchanged. The existing
  `dataEntries` cases still pass.
- `builder.test.tsx`
  - The sequence card case expects "Tissue testing" and "Liquid biopsy" (capitalised list items) and
    the Remove `aria-label`s "Remove tissue testing from first report of c4" (disabled) and
    "Remove liquid biopsy from later report of c4" (not disabled).
  - New: a data card heading reads `aria-label="Serial reports (two or more)"`.
  - New: `render({...EMPTY, criteria: [sequence]})` matches a disabled same-report checkbox and
    contains the title text; `render({...EMPTY, criteria: [alt]})` does not disable it;
    `render({...EMPTY, scope: "report"})` does not disable it.
  - New: `render({...EMPTY, scope: "report", criteria: [alt]})` does not contain ">Then…</button>".
  - New: static render of `<AlterationEditor d={{...alt, mode: "tested_negative"}} …/>` lists only
    the `mutation` class checkbox and the hint; with `mode: "include"` it lists all four classes
    and no hint.
- `answer.test.tsx`: new case, `result({patients: 9, reports: null})` contains "reports not shown"
  and not "&lt;5</span> reports"; the existing cases still pass.
- `compare.test.tsx`: the shared fixture (blank 2023 and 2025 cells) contains
  "Blank: no patients that year for that version."; the `shownOnly` render (no years) does not.
  A suppressed column (`patients: null`, `by_year: []`, as the server returns it) next to a shown
  one renders `<5` in its year cells and no "Blank:" legend.
- New `app.test.tsx`: static renders of `FeasibilityPanel`. With `statement=""`: contains
  "Recounting…", no `<textarea`, a Copy button with `disabled=""`, a Close button. With a
  statement: a textarea holding it and an enabled Copy. With `copied` true: "Copied".

## Risks

- **Doc-only privacy items.** Goals 2 and 6 name gaps rather than close them. That is the issue's
  instruction; #72 may widen `neighbours()` later, and then these accepted-risk lines need
  re-checking in the same PR.
- **Pivot cleared silently.** After "Then…" on a pivot-axis card, the pivot disappears without a
  message, as it already does for `remove_criterion` and `set_mode`. The Pivot tab then shows its
  axis selects with no pivot, as after those two operations.
- **Label case.** Lower-case data labels mid-sentence ("met: liquid biopsy; KRAS mutation") match
  how `specimen` labels already read. Anyone matching old label strings (saved feasibility text in
  grants) sees new wording; nothing stores labels, so no data migrates.
- **openapi regeneration** must run from this worktree with `bun run gen`; a hand edit would drift
  from what `test_app.py` compares.
