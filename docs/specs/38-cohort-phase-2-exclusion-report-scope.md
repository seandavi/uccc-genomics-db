# Spec #38: cohort phase 2: exclusion, report scope, data and sequence, privacy additions, compare

Part of #23, phase 2 of `dashboard/COHORT_DISCOVERY.md` (§3.1 modes, §3.3 top bar, §3.6 privacy
additions, §4). Builds on #34 (the cohort module, `docs/specs/34-cohort-module-definition-operations.md`),
#35 (`genomics-app`) and #37 (Discover, `docs/specs/37-discover-react-app-for-building-cohorts.md`).
Labels: `seam`, `review:security`.

All examples and fixture values are synthetic. Gene symbols, OncoTree codes and marker names are
public vocabulary, not patient data. No real counts appear. The worked numbers below are those of
the synthetic test mart.

## Goal

1. The cohort definition gains criterion `mode` (`include`, `exclude`, `tested_negative`),
   `scope: "report"`, the `data` and `sequence` kinds, and an optional per-criterion `vendor`. The
   compiler turns each into SQL over `mart.*`.
2. Suppression gains the §3.6 additions that phase 1 did not have:
   - the **A ∧ ¬B rule** for exclusions: a count is hidden when it differs by 1–4 from the same
     count without an exclusion;
   - the **tested-negative rule**: the same check against the cohort with a `tested_negative`
     criterion made a plain `exclude`;
   - the **union rule**: the same check against the cohort with one value taken out of a population
     field that lists two or more values, or with one end year taken off a year range;
   - the **scope rule**: for a report-scope definition with two or more criteria, or with any
     negated criterion, the same check against the cohort at patient scope. The two differ by the
     patients whose criteria match only on different reports (or, for one exclusion, who have B on
     one report and a report without it), a group no include query can express. One include
     criterion counts the same at both scopes and gets no scope neighbour.

   Both are one mechanism, the *neighbour check* (below). The funnel delta rule and two-way pivot
   suppression already exist (#34). They stay, and they get attack tests in phase 2 shapes.
3. Discover gets the include / exclude / tested-negative toggle, a "same report" switch, `data`
   and `sequence` criteria, a vendor choice, **Compare** (2–4 versions side by side) and the
   **feasibility statement** generator.

Done when COHORT_DISCOVERY questions 10, 11, 14, 17 and 18 are answered by tests on a synthetic
mart, and each suppression rule has a test that runs the differencing attack and shows the rule
defeats it.

## Non-goals

- **Request data** stays out (the PHI path, #16).
- `sequence.min_gap_days` is not built. "Later" means a strictly later collection date. A gap
  would need its own fixed cut points (§3.1: no free numbers), and no question needs it.
- No yes/no "criterion matched" pivot axis. Question 10's 2×2 is two counts: the co-alteration
  included, then excluded.
- The union rule does **not** cover OR lists inside a criterion (several genes, protein changes or
  `any_of` members). They are accepted under the audit log, as in phase 1 (Risks).
- Differencing that combines three or more queries is accepted under the audit log (Risks).
- No change to `cohort_api.py` (the public phase 1 API), `server.py`, `authen.py`, `saved.py`,
  `deid.py`, id hashing or date shifting. `research_id` and `report_id` are unchanged. They are
  read only inside SQL and never returned.
- Discover keeps its versions in `localStorage` (#37). Compare picks from those versions, not
  from saved cohorts, because Discover does not call `/api/saved*` yet.
- No new dependency (Python or web).

## Decisions the issue left to the spec

1. **Union rule: applied.** This is the issue's default. It covers every population field that
   lists two or more values (`oncotree`, `organ`, `sex`, `age_band`, `vendor`, `assay_class`), and
   `years` when `from < to`, because a range is a union of years.
2. **`tested_negative` with several genes means every gene.** The patient has no matching finding
   for any listed gene, and each listed gene was reported wild-type or as a pertinent negative.
   This is the negation of the OR the criterion's genes mean (De Morgan). "RAS wild-type" means
   KRAS and NRAS both tested negative.
3. **`tested_negative` applies to `alteration` criteria only, without `aa`, with `class` `[]` or
   `["mutation"]`.** The evidence (`mart.fact kind = 'tested_negative'`) is per gene: Caris
   wild-type variant records and FMI pertinent negatives. It says nothing about one protein change,
   a copy-number change or a fusion.
4. **At most 3 negated criteria** (`exclude` or `tested_negative`) per definition. The neighbour
   check tries every non-empty subset of them (at most 7 extra statements), and each
   `tested_negative` criterion made a plain `exclude` (at most 3 more). Question 11 needs 3.
5. **At most 32 neighbours per count.** That is ≤ 7 exclusion subsets, plus ≤ 3 `tested_negative` swaps, plus 2 for a year range, plus 1 for report scope,
   plus one per value in each multi-value population field. A definition that needs more is a 400
   when it is counted, not when it is parsed. Saved cohorts (#36) re-validate their stored
   definitions on read, and phase 1 allowed up to 100 OncoTree codes, so parse-time rejection would
   break stored cohorts. On a synthetic mart of ~700k facts one count statement takes ~20 ms, so 33
   statements stay under a second.
6. **Loosen suggestions are only offered for definitions with no neighbours** (include-only, with
   no multi-value population field, no year range and not report scope with two or more criteria or a negated criterion). A suggestion is itself a count, and for a
   definition with neighbours it would need its own neighbour checks. `CountResult` gains
   `loosen_offered: bool` so the page can say why there are none.
7. **Question 17 needs a per-criterion `vendor`** (`"caris"`, `"fmi"` or null). A vendor × vendor
   concordance pivot pairs two criteria on the same patient, and only a vendor on each criterion
   tells "Caris TMB" from "FMI TMB" apart. The population's `vendor` filter cannot do it, because
   it restricts every criterion at once.
8. **`data.has` is one value, not a list.** It mixes per-report facts (`wts`, `liquid`, `tissue`)
   with patient-level ones (`both_vendors`, `serial`), and an OR across the two has no clear
   accrual year.
9. **Negated criteria give no accrual year.** A patient's year is the latest, over the include
   criteria, of the earliest matching year (as in #34). With no include criterion it is the
   patient's first in-population year.
10. **Compare uses the local version history** (`localStorage`, #37). The user ticks 2–4 versions.

## Deviations from the design docs (the implementer updates them in the same PR)

- `COHORT_DISCOVERY.md` §3.1: the `data` row's `has` is a single value. `sequence` has `first` and
  `then` (1–4 members each, AND on one report) and no `min_gap_days`. Leaf criteria take `vendor`.
  `tested_negative` follows decisions 2–3. There are at most 3 negated criteria. Add a "Phase 2
  (#38)" paragraph after the phase 1 paragraph, drop "phase 2" from the rejection list, and add
  the `vendor` field to the kinds table.
- §3.3: the "same report" lock is one switch for the definition (`scope` is a definition field),
  not one per card. Compare picks local versions (decision 10). Loosen is offered only per
  decision 6.
- §3.6: the multi-select row's "Open" becomes the neighbour check (decision 1). The exclusion
  row's control is stated as the neighbour check. Add a row: three-query differencing is accepted
  under the audit log. The `loosen[]` row gains decision 6.
- §4 phase 2: note that Request data is still deferred (#16).
- §5 open question 3: answered by #38 (ship with the rule).
- `docs/ARCHITECTURE.md` decision 2: add `set_scope` to the operations listed.
- `README.md` `mart.*` paragraph: `mart.report` gains `collected_on`. The sentence "the
  `data`/`sequence` criteria are not in the mart" becomes "`data` and `sequence` criteria read
  `mart.report` (`has_wts`, `assay_class`, `vendor`, `collected_on`)".

## Design

### Files

| File | Change |
|---|---|
| `src/uccc_genomics/sql/mart.sql` | `mart.report` gains `collected_on DATE` as its **last** column |
| `mcp/src/uccc_genomics_mcp/cohort/definition.py` | modes, `vendor`, `Data`, `Sequence`, `scope: "report"`, validation, `SetMode` / `SetScope` operations, `neighbours()`, new notes |
| `mcp/src/uccc_genomics_mcp/cohort/compile.py` | negated criteria, `data`, `sequence`, `vendor`, report scope |
| `mcp/src/uccc_genomics_mcp/cohort/suppress.py` | neighbour check in `suppress_count` / `suppress_pivot`; `CountResult.loosen_offered` |
| `mcp/src/uccc_genomics_mcp/cohort/queries.py` | run the neighbours; loosen only without neighbours |
| `mcp/src/uccc_genomics_mcp/cohort/vocabulary.py` | `check` walks `sequence` members |
| `mcp/src/uccc_genomics_mcp/app.py` | `INSTRUCTIONS` and the `count` / `pivot` tool docstrings (one sentence each) |
| `web/openapi.json`, `web/src/api.gen.ts` | regenerated with `cd web && bun run gen` |
| `web/src/types.ts` | `SeqMember` alias |
| `web/src/cohort.ts` | labels for modes / data / sequence / vendor, `DATA_ENTRIES`, `dataEntries`, `modesFor`, `pivotAxes` filter, `feasibility` |
| `web/src/Builder.tsx` | mode select, same-report switch, vendor select, data entries, sequence card ("Then…") |
| `web/src/Answer.tsx` | loosen message when not offered; suppressed wording |
| `web/src/Compare.tsx` | **new**: version picker and comparison table |
| `web/src/App.tsx` | top-bar Compare and Feasibility statement buttons and panels |
| `tests/test_cohort.py` | `Mart.report` gains `collected_on`; changed assertions (listed in the test plan) |
| `tests/test_cohort_phase2.py` | **new**: phase 2 mart, questions 10/11/14/17/18, attack tests |
| `tests/test_app.py` | parity cases for the new modes, scope and operations |
| `tests/test_pipeline.py` | `mart.report` column list and `collected_on` value |
| `web/src/cohort.test.ts`, `web/src/answer.test.tsx`, `web/src/builder.test.tsx`, `web/src/compare.test.tsx` (new) | `bun test` |
| `dashboard/COHORT_DISCOVERY.md`, `docs/ARCHITECTURE.md`, `README.md` | per Deviations |

### Mart: `mart.report.collected_on`

In `mart.sql` add `r.collected_on` to `base` and `collected_on` as the last column of the final
`SELECT` (after `has_wts`). The source is `unified.report.collected_on`: Caris
`specimen.collected_on` and FMI `collection-date` (PLAN.md mapping), already shifted per patient
by `deid` (±182 days, one offset per patient, so intervals within a patient are kept). The column
is used only to compare two reports of the same patient (`sequence`). It is never a dimension, a
pivot axis or an output.

### `definition.py`

#### Constants

```python
Mode = Literal["include", "exclude", "tested_negative"]
NEGATED = ("exclude", "tested_negative")
MAX_NEGATED = 3
MAX_NEIGHBOURS = 32
DataHas = Literal["wts", "liquid", "tissue", "both_vendors", "serial"]
REPORT_DATA = ("wts", "liquid", "tissue")          # per report; the other two are per patient
Vendor = Literal["caris", "fmi"]
```

Delete `DEFERRED_KINDS`, `_reject_deferred` and `_reject_deferred_all`, and their `field_validator`
uses on `Definition.criteria`, `AnyOf.of`, `AddCriterion` and `UpdateCriterion`. Delete the
`scope == "report"` rejection in `Definition._scope`. `version != 1` is still rejected.

#### Models

```python
class _Criterion(BaseModel):
    id: str | None = None
    mode: Mode = "include"

class _Leaf(_Criterion):
    vendor: Vendor | None = None          # only this vendor's reports can match

class Alteration(_Leaf): ...             # unchanged fields; base becomes _Leaf
class Biomarker(_Leaf): ...
class Ihc(_Leaf): ...
class Expression(_Leaf): ...
class Specimen(_Leaf): ...
class Actionability(_Leaf): ...

class Data(_Leaf):
    kind: Literal["data"]
    has: DataHas

Leaf = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability,
                 Field(discriminator="kind")]                     # any_of members: unchanged set
SeqMember = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability | Data,
                      Field(discriminator="kind")]

class AnyOf(_Criterion): ...             # unchanged fields

class Sequence(_Criterion):
    kind: Literal["sequence"]
    first: Annotated[list[SeqMember], Field(min_length=1, max_length=4)]   # AND, on one report
    then: Annotated[list[SeqMember], Field(min_length=1, max_length=4)]    # AND, on one strictly later report

Criterion = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability | Data
                      | AnyOf | Sequence, Field(discriminator="kind")]

class Definition(BaseModel):
    ...
    scope: Literal["patient", "report"] = "patient"
```

`Sequence.first` and `Sequence.then` are each sorted by the canonical JSON of their members, as
`AnyOf.of` is (`_order_independent`), so member order never changes `cohort_id`.

#### Validation (each failure raises `DefinitionError` with the message shown)

Criterion level:

- `Data`: `vendor` set with `has` in (`both_vendors`, `serial`) →
  `"vendor does not apply to data '<has>'"`.
- `AnyOf` and `Sequence` members: `id` must be None (existing message for `any_of`; for
  `sequence`: `"sequence members take no id"`). `mode` must be `include` →
  `"<kind> members are include-only; set mode on the <kind> itself"`.
- `Sequence` members of kind `data` need `has` in `REPORT_DATA` →
  `"sequence members can only use data 'wts', 'liquid' or 'tissue'"`.
- `Sequence.mode` must be `include` → `"a sequence criterion is include-only"`.
- `mode == "tested_negative"` needs `kind == "alteration"`, `aa == []` and `class_` in
  (`[]`, `["mutation"]`) → `"tested_negative applies to an alteration criterion without aa, of class mutation or any class"`.

Definition level (`Definition._check`, after the existing checks):

- More than `MAX_NEGATED` criteria with `mode` in `NEGATED` →
  `"criteria: at most 3 exclude or tested_negative criteria"`.
- `scope == "report"` with a `sequence` criterion, or with `data.has` in (`both_vendors`,
  `serial`) → `"criteria.<id>: '<kind or has>' spans several reports and cannot be used with scope 'report'"`.
- Pivot axis on a criterion that is negated → `"pivot.<field>: an exclude or tested_negative criterion cannot be a pivot axis"`.
  On a `data` or `sequence` criterion → `"pivot.<field>: a <kind> criterion cannot be a pivot axis"`.
  The specimen rule stays.

#### `cohort_id`

Unchanged code. `_canon` uses `exclude_defaults=True`, so `mode: "include"`, `vendor: None` and
`scope: "patient"` leave every phase 1 id unchanged. The pinned id in
`test_cohort_id_stable` must still pass unchanged.

#### Operations

```python
class SetMode(_Op):
    op: Literal["set_mode"]
    id: str
    mode: Mode

class SetScope(_Op):
    op: Literal["set_scope"]
    scope: Literal["patient", "report"]

Operation = Annotated[AddCriterion | RemoveCriterion | UpdateCriterion | SetMode | SetPopulation
                      | SetBreakdown | SetPivot | SetScope | Rename, Field(discriminator="op")]
```

In `apply`:

- `set_mode`: unknown id → `"unknown criterion id '<id>'"`. Set `criteria[pos]["mode"]`. If the
  new mode is negated and `pivot` references the id, set `pivot` to None (as `remove_criterion`
  does).
- `set_scope`: replace `scope`.

The result is re-validated as today, so an invalid mode (for example `tested_negative` on an
`ihc`) raises the validation message.

#### `neighbours`

```python
class Neighbour(NamedTuple):
    definition: Definition
    step: list[int]      # step[k]: this neighbour's funnel index that pairs with step k of d

def neighbours(d: Definition) -> list[Neighbour]:
    """The definitions one edit away whose counts a user could subtract from d's: d without each
    non-empty subset of its negated criteria; d with one tested_negative criterion made a plain
    exclusion (the difference is the patients with no result for the gene); d with one value taken out of a population field that
    lists two or more; d with one end year taken off a year range (from < to); a report-scope d with
    two or more criteria, or any negated criterion, at patient scope (the difference is the patients whose criteria match only on
    different reports). Raises DefinitionError if there are more than MAX_NEIGHBOURS."""
```

- Build each neighbour from `d.model_dump(mode="json", by_alias=True)`, edit it and run
  `Definition.model_validate` (never `model_copy`). `name`, `breakdown`, `pivot` and `scope` are
  kept. A pivot never references a negated criterion, so it stays valid.
- Exclusion subsets: `negated = [c.id for c in d.criteria if c.mode in NEGATED]`. For each
  `S` in `itertools.combinations(negated, r)`, `r = 1..len(negated)`, drop those criteria.
  `step[k] = k - (number of criteria in d.criteria[:k] whose id is in S)`.
- Mode swaps: for each `tested_negative` criterion in `d.criteria` order, `d` with that criterion's
  `mode` set to `"exclude"`. `step[k] = k`. `tested_negative` is ¬B ∧ T (every listed gene reported
  wild-type), so without this neighbour the cohort with the exclusion minus the cohort with
  tested-negative is A ∧ ¬B ∧ ¬T, the patients with no result at all, which no include query can
  express. Only the `tested_negative` side gets the neighbour; its count is the one hidden.
- Population values: for each field in `POP_DIMS` (in that order) with `len(values) >= 2`, and each
  value in it (sorted order), drop that value. `step[k] = k`.
- Years: if `years` is set and `years[0] < years[1]`, add `[from + 1, to]` and then
  `[from, to - 1]`. `step[k] = k`.
- Scope: if `d.scope == "report"` and (`len(d.criteria) >= 2` or any criterion is negated), add `d` with `scope` set to `"patient"`.
  `step[k] = k`. A patient-scope count is at least as large as the report-scope count for include
  criteria, and the two differ for exclusions in either direction, so without this neighbour the
  two counts of one definition (one click apart in the Builder, side by side in Compare) could
  differ by 1 to 4 with both shown. Only the report-scope side gets the neighbour. With one
  criterion the two scopes count the same, so there is none.
- More than `MAX_NEIGHBOURS` → `DefinitionError("population: this cohort needs <n> privacy checks (one per combination of exclusions, one per tested-negative criterion, one per value in a field that lists two or more, two for a year range, one for report scope); at most 32 are allowed. Use fewer values or a coarser field such as organ")`.
- Order is deterministic (subsets, then mode swaps, then population, then years, then scope). It is part of the function's
  contract, so tests can index into it.

#### Data notes

Add these keys to `NOTES`, after `fda` and before `absent`, in this order:

| key | triggered by | text |
|---|---|---|
| `exclude` | any criterion with `mode` in `NEGATED` | `An exclusion drops patients with a matching finding on any of their in-population reports (on the same report when all criteria must match on one report); a gene that was not tested counts as not found.` |
| `tested_negative` | any `tested_negative` criterion | `Tested negative also needs every listed gene reported wild-type (Caris) or as a pertinent negative (FMI lists only some genes, so FMI patients are under-counted).` |
| `sequence` | any `sequence` criterion | `Report order uses collection dates, shifted per patient for de-identification so intervals are kept; reports without a date are never ordered, and same-day reports are not later.` |
| `both_vendors` | a `data` criterion with `has == "both_vendors"` | `Patients are linked across vendors by MRN, or name and birth date when an FMI report has no MRN; tested by both vendors is a lower bound.` |
| `neighbours` | `neighbours(d)` is non-empty (computed without the cap) | `A count that differs by 1 to 4 from the same count without an exclusion, with a tested-negative criterion as a plain exclusion, without one of the listed population values or end years, or matched across reports instead of on one report, is hidden so a small group cannot be worked out by subtraction; suggestions to loosen are not offered.` |

`data_notes` keeps walking `any_of` members and now also walks `sequence` members
(`first + then`) for the existing `ihc`, `expression`, `specimen` and `fda` triggers. For the
`neighbours` trigger it uses a private `_neighbour_count(d) -> int` that `neighbours()` also uses
for its cap, so `data_notes` never raises.

### `compile.py`

Caller values still enter only as `$name` parameters. Everything else interpolated into the text
comes from code: parameter and CTE names, the column names already validated, and the fixed
predicates for `data.has` below.

#### Vendor

`_fact_cond(leaf, P)` and `_specimen_conds(leaf, P)` add `f.vendor = $P_vendor` to every
condition when `leaf.vendor` is set. `_data_pred` adds `p.vendor = $P_vendor`.

#### Report predicates

```python
def _exists(cond: str, alias: str = "p") -> str          # f.vendor = {alias}.vendor AND f.report_id = {alias}.report_id
def _leaf_pred(leaf, P: str, alias: str = "p") -> tuple[str, dict]
def _data_pred(leaf, P: str, alias: str = "p") -> tuple[str, dict]
def _members_pred(members, P: str, alias: str) -> tuple[str, dict]    # AND of member predicates, member j prefix f"{P}{j}"
```

`_data_pred` for `REPORT_DATA` uses these fixed predicates: `wts` → `{alias}.has_wts`, `liquid` →
`{alias}.assay_class = 'liquid'`, `tissue` → `{alias}.assay_class = 'tissue'`. `_leaf_pred`
dispatches `data` to `_data_pred`. The `pop` CTE selects `collected_on` as well.

#### Patient scope (`_ctes`, `scope == "patient"`)

For criterion `i` with prefix `k{i}`:

| kind / mode | CTEs |
|---|---|
| leaf, `any_of`, `data` in `REPORT_DATA` | `m{i}` as today (any mode); `q{i} AS (SELECT research_id, min(year) AS yr FROM m{i} GROUP BY research_id)` |
| `sequence` | `m{i} AS (SELECT t.research_id, t.vendor, t.report_id, t.year FROM pop t WHERE <then pred, alias t, prefix k{i}t> AND EXISTS (SELECT 1 FROM pop p WHERE p.research_id = t.research_id AND p.collected_on < t.collected_on AND <first pred, alias p, prefix k{i}f>))`; `q{i}` as above |
| `data` `both_vendors` | `q{i} AS (SELECT research_id, max(y) AS yr FROM (SELECT research_id, vendor, min(year) AS y FROM pop GROUP BY 1, 2) GROUP BY 1 HAVING count(*) >= 2)`; no `m{i}` |
| `data` `serial` | `q{i} AS (SELECT research_id, list_sort(list(year) FILTER (WHERE year IS NOT NULL))[2] AS yr FROM pop GROUP BY 1 HAVING count(*) >= 2)`; no `m{i}` |
| `tested_negative` (also) | `t{i} AS (SELECT p.research_id FROM pop p JOIN mart.fact f ON f.vendor = p.vendor AND f.report_id = p.report_id WHERE f.kind = 'tested_negative' AND list_contains($k{i}_gene, upper(f.key)) [AND f.vendor = $k{i}_vendor] GROUP BY p.research_id HAVING count(DISTINCT upper(f.key)) = len($k{i}_gene))` |

```python
def _from(d: Definition, k: int) -> str:
    """'pp' joined with the first k criteria: include -> JOIN q{i} USING (research_id);
    exclude -> ANTI JOIN q{i} USING (research_id); tested_negative -> ANTI JOIN q{i} USING
    (research_id) SEMI JOIN t{i} USING (research_id)."""
```

- `cohort AS (SELECT pp.research_id, <yr> AS yr FROM <_from(d, n)>)`. `<yr>` is
  `greatest(q{i}.yr, …)` over the **include** criteria, or `pp.yr` when there are none.
- `hit`: today's `EXISTS (… m{i} …)` OR over the include criteria **that have an `m{i}`**. With
  none, `hit AS (SELECT p.* FROM pop p JOIN cohort USING (research_id))`.
- Funnel step k: `SELECT count(*) FROM <_from(d, k)>`.

DuckDB 1.5 accepts `JOIN … USING`, `ANTI JOIN … USING` and `SEMI JOIN … USING` in one chain, and
`list_sort(list(x) FILTER (WHERE …))[2]` (checked on 1.5.5).

#### Report scope (`_ctes`, `scope == "report"`)

```
rk AS (SELECT p.research_id, p.vendor, p.report_id, p.year, <b_0> AS k0, …, <b_{n-1}> AS k{n-1} FROM pop p)
cohort AS (SELECT research_id, min(year) AS yr FROM rk WHERE <all> GROUP BY research_id)   -- n = 0: SELECT research_id, yr FROM pp
hit AS (SELECT p.* FROM pop p JOIN rk ON rk.vendor = p.vendor AND rk.report_id = p.report_id WHERE <all>)
```

`<all>` is `k0 AND … AND k{n-1}` (`true` when n = 0). `b_i` is the criterion's report predicate
(alias `p`): include → `(<pred>)`; exclude → `NOT (<pred>)`; tested_negative →
`NOT (<pred>) AND (SELECT count(DISTINCT upper(f.key)) FROM mart.fact f WHERE f.vendor = p.vendor AND f.report_id = p.report_id AND f.kind = 'tested_negative' AND list_contains($k{i}_gene, upper(f.key))) = len($k{i}_gene)`.
Funnel step k: `SELECT count(DISTINCT research_id) FROM rk WHERE <first k>`. Step 0 equals the
`pp` count.

`_funnel_rows(d, null_cols)` branches on scope. `compile()` and `compile_pivot()` keep their
signatures and row shapes. In `compile_pivot`, two different criterion axes pair on
`vendor`/`report_id` (same report) under report scope, and on `research_id` under patient scope,
as today.

### `suppress.py`

```python
@dataclass
class RawNeighbour:
    raw: "RawCount"
    step: list[int]

@dataclass
class RawCount:
    ...                                                        # existing fields
    neighbours: list[RawNeighbour] = field(default_factory=list)

@dataclass
class RawPivotNeighbour:
    raw: "RawPivot"
    step: list[int]

@dataclass
class RawPivot:
    ...
    neighbours: list[RawPivotNeighbour] = field(default_factory=list)

class CountResult(BaseModel):
    ...
    loosen_offered: bool = True        # False when the definition has neighbours (decision 6)
```

`loosen_offered` defaults to True so snapshots stored before #38 still validate.

The neighbour check is a primary suppression, like the floor. It runs before the line rules:

```python
def _near(a: int, b: int) -> bool:
    return 0 < abs(a - b) < MIN_CELL
```

`suppress_count(d, raw)`:

1. If `len(raw.neighbours) != len(neighbours(d))`, raise `ValueError("raw.neighbours does not match neighbours(d)")`.
   A caller cannot skip the checks.
2. `hidden_steps = {k for k in range(len(raw.funnel)) for n in raw.neighbours if _near(raw.funnel[k], n.raw.funnel[n.step[k]])}`.
3. `_funnel(raw.funnel, hidden_steps)`: a step in `hidden_steps` is None and does not become the
   delta rule's last shown step. The default is an empty set, so phase 1 callers are unchanged.
4. If the cohort is shown, before `_suppress_line`:
   - `reports` is None if any neighbour has `_near(raw.reports, n.raw.reports)`;
   - year `y` is None if `_near(raw.by_year[y], n.raw.by_year.get(y, 0))` for any neighbour;
   - breakdown cell `(dim, v)` is None if `_near(raw.breakdowns[dim][v], n.raw.breakdowns.get(dim, {}).get(v, 0))`;
   - denominator `(dim, v)` likewise against `n.raw.denominators`.

   Then run the existing line rules unchanged. A value hidden here counts as hidden in its line.
5. `loosen_offered = not raw.neighbours`. Loosen suggestions are built as today only when
   `loosen_offered`.

`suppress_pivot(d, raw)`: the same length check against `neighbours(d)`. `patients` comes from
`_funnel(raw.funnel, hidden_steps)[-1]`. Before the fixed-point loop, a cell `(r, c)`, a row total
`r` or a column total `c` is None if it is `_near` the neighbour's same key (absent = 0). Then the
loop runs unchanged.

Update the module docstring: every number has also passed the neighbour check. Name what that
check does not cover: OR lists inside a criterion, three-query differencing, and breakdown cell
against denominator, which is already accepted.

### `queries.py`

```python
def _run_pivot(con, d: Definition) -> RawPivot          # factored out of pivot()

def count(d: Definition) -> CountResult:
    vocabulary().check(d)
    near = neighbours(d)                                 # raises (400) before any query
    con = get_db()
    try:
        raw = _run_count(con, d)
        raw.neighbours = [RawNeighbour(_run_count(con, n.definition), n.step) for n in near]
        result = suppress_count(d, raw)
        if not near and (result.patients is None or raw.funnel[-1] < MIN_CELL):
            ...                                          # loosen as today
        return result
    finally:
        con.close()

def pivot(d: Definition) -> PivotResult                  # same shape with _run_pivot and RawPivotNeighbour
```

A neighbour's definition is a subset of `d`'s values, so it needs no vocabulary check. Rate limit
and audit (`app.py`) still count one call per `count` / `pivot`.

### `vocabulary.py`

`check` walks `sequence` members (`first`, then `then`) with paths
`criteria.<id>.first.<j>` / `criteria.<id>.then.<j>`, and checks a member as it checks a leaf.
`data` has nothing to check. `tested_negative` criteria are `alteration` criteria and are checked
as such.

### `app.py`

- `INSTRUCTIONS` gains: `"A criterion's mode is include (default), exclude or tested_negative; scope 'report' makes every criterion match on one report. A count can also be null because it differs by 1-4 from the same cohort without an exclusion or one population value (so a small group cannot be worked out by subtraction)."`
- The `count` and `pivot` tool docstrings: change "null means suppressed" to "null means suppressed
  (under 5, or hidden so a small count cannot be worked out by subtraction)".
- No new route or tool. `apply_op` / `POST /api/apply` take the new operations through `Operation`.
  A `neighbours()` cap error is a `DefinitionError`, so it becomes a 400 / tool error through the
  existing handlers.

### What leaves the host, and the rule each output applies

| Output | Rule |
|---|---|
| `POST /api/cohort`, MCP `count`, snapshots | floor 5; neighbour check (A ∧ ¬B and union); funnel delta; line rule on years, breakdown cells and denominators; whole-cohort rule; loosen only without neighbours, under its existing rules |
| `POST /api/pivot`, MCP `pivot` | floor 5; neighbour check on cells and margins; two-way line rule to a fixed point; whole-cohort rule; `sub`/`val` labels under 5 become `other` |
| `GET /api/options`, MCP `search_vocabulary` | unchanged: floored values, no counts |
| `POST /api/apply`, `/api/schema` | definitions and schemas only, no counts |

Nothing returns `collected_on`, a date, `research_id` or `report_id`.

### Discover (`web/`)

Regenerate `web/openapi.json` and `web/src/api.gen.ts` with `cd web && bun run gen` after the
Python changes. `types.ts` adds `export type SeqMember = S["Sequence"]["first"][number];` and
`export type Mode = Criterion["mode"];`.

#### `cohort.ts`

```ts
export const DATA_LABELS: Record<string, string> = {
  wts: "Has whole-transcriptome sequencing", liquid: "Has a liquid biopsy", tissue: "Has tissue testing",
  both_vendors: "Tested by both Caris and FMI", serial: "Two or more reports",
};
export const DATA_ENTRIES: Option[]          // one {field: "data.has", parent: null, value} per DATA_LABELS key
export function dataEntries(q: string): Option[]   // entries whose label contains q (case-insensitive); [] for blank q
export function modesFor(c: Criterion): Mode[]     // sequence: ["include"]; alteration without aa and class [] or ["mutation"]: all three; else ["include", "exclude"]
export function feasibility(d: Definition, r: CountResult, years: readonly [number, number] | null): string
```

`Mode` is `Criterion["mode"]`, exported from `types.ts` (generated types). `cohort.ts` also exports
`REPORT_DATA` (`["wts", "liquid", "tissue"]`, the `data.has` values judged per report), which
`Builder.tsx` imports for the "Then…" button and the scope switch.

- `criterionLabel`: `data` → `DATA_LABELS[has]`. `sequence` → `` `${first labels joined " and "}, then later ${then labels joined " and "}` ``.
  A leaf with `vendor` gets ` (Caris)` or ` (FMI)`. Mode wraps the label: exclude →
  `` `no ${label}` ``; tested_negative → `` `${genes joined " and "} tested negative` ``. The
  funnel's `∧ …` prefix is unchanged.
- `newCriterion` handles `data.has`:
  `{id: null, mode: "include", kind: "data", has: e.value, vendor: null}`. Every leaf constructor
  sets `vendor: null`.
- `fieldLabel` gives `"Data available"` for `data.has`.
- `pivotAxes` skips criteria whose `mode !== "include"` and the `data` and `sequence` kinds.
- `feasibility` (pure, numbers only from `r` and `years`; a null count claims no size, since it is
  under 5 or hidden by the neighbour, funnel or line rules, whatever its size: the denominator reads
  `a suppressed number of`, the criteria count `a suppressed number`, else `fmtCount(x)`):

  ```
  {window} the UCCC sequenced {n(r.denominator)} patients{ in <populationLabel> unless "All patients"}
  [, of whom {n(r.patients)} met: {criterionLabel of each criterion, joined "; "}]      -- only if criteria
  [ (about {perYear.toFixed(1)} a year)]                                              -- only if accrualPerYear(r.patients, years) != null
  .[ Every criterion was met on the same report.]                                     -- only if scope "report"
   Counts are distinct de-identified patients from Caris and FMI reports; counts under {r.min_cell}, and counts that would let one be worked out by subtraction, are not shown. {r.notes joined " "}
  ```

  `{window}` is `Between {years[0]} and {years[1]},` or `To date,` when `years` is null.

  The same reasoning changes the `Answer.tsx` live region for a null `patients` from "fewer than 5
  patients" (spec 37) to "patient count not shown".

#### `Builder.tsx`

- Criterion card: `<select aria-label="Mode of {id}">` with the options of `modesFor(c)`, labelled
  "Include", "Exclude" and "Tested negative". On change it sends `{op: "set_mode", id, mode}`.
- Criteria heading: a checkbox "All criteria on the same report" (checked when
  `scope === "report"`). It sends `{op: "set_scope", scope}`.
- `searchAll` prepends `dataEntries(q)` (after `biomarkerEntries(q)`).
- Leaf editors (every `EditorBody` kind but `any_of`): `<select aria-label="Vendor">` with "any
  vendor" (null), "Caris" and "FMI". For `data` with `both_vendors`/`serial` it is not shown. The
  `data` editor otherwise has only the vendor select.
- "Then…" button on an include card of a leaf kind, or of `data` with `has` in `REPORT_DATA`. It
  opens the typeahead (non-population entries, `data` limited to `REPORT_DATA`). Picking an entry
  sends `update_criterion` with
  `{kind: "sequence", id, mode: "include", first: [leaf(c)], then: [leaf(picked)]}`.
- Sequence card: two member lists, "First report" and "Later report". Each member has a ×, which is
  disabled when it is the side's only member. Each side has an "And on the same report…" typeahead
  (hidden at 4 members). Edits go through `update_criterion`. No Edit button (as for `any_of`).

#### `Answer.tsx`

- `Loosen`: when `r.loosen_offered` is false and `r.patients == null`, show
  "Too few patients to show, or hidden so a small group cannot be worked out by subtraction." and
  nothing else. When `loosen_offered` is false and patients are shown, render nothing. The
  existing texts are kept when `loosen_offered` is true.

#### `Compare.tsx` (new)

```tsx
export interface CompareColumn {
  label: string; result: CountResult | null; error: string | null;
  window?: readonly [number, number] | null;   // the year span of this version's accrual
}
export function CompareTable({columns, minCell}: {columns: CompareColumn[]; minCell: number})   // pure
export function Compare({versions, transport, years, onClose}: {
  versions: Version[]; transport: Transport; years: readonly [number, number] | null; onClose: () => void;
})
```

- `Compare` lists the versions as checkboxes (`v{n} · {name or "Untitled"}`). The newest two are
  ticked at first. "Count" is enabled with 2–4 ticked, and runs `transport.count` for each one
  (`Promise.allSettled`). A failed one shows `describeError` in its column.
- `CompareTable` (a `GridTable`-style scrolling table with a `<caption>`) has one column per
  definition. Rows: Patients, Population (denominator), Share (`pct`), Accrual a year
  (`accrualPerYear` over each column's `window`, which `Compare` sets to the definition's
  `population.years`, falling back to `years`), then one row per year
  in the union of the results' `by_year` years, with each column's `patients` for that year (blank
  when that result has no such year). Every count goes through `Count` (null → "<5"). Each column
  header's `title` is the `cohort_id`.
  Under the table, when any count is null, the same legend line as the Answer funnel
  (`<5: fewer than 5 patients, or hidden so that a small count cannot be worked out by
  subtraction.`), because a hover title does not reach a touch screen and two versions one edit
  apart are exactly where a neighbour-hidden count shows.

#### `App.tsx`

Two top-bar buttons, "Compare" and "Feasibility statement", each with `aria-expanded`. They toggle
a panel under the header:

- Compare: `<Compare versions={hist.versions} …/>`.
- Feasibility statement: disabled until there is an answer and it is not stale. Shows
  `<textarea readOnly aria-label="Feasibility statement">` holding
  `feasibility(answer.d, answer.r, answer.d.population.years ?? options?.years ?? null)`, and a
  "Copy" button with the same clipboard / fallback behaviour as Share link.

`policy.test.ts` keeps passing: there is no new `fetch`, no URL and no SQL.

## Acceptance criteria

- [ ] `parse` accepts `mode` `exclude` / `tested_negative`, `scope: "report"`, `data`,
      `sequence` and leaf `vendor`, with each validation rule above raising its message.
- [ ] `cohort_id` of every phase 1 definition is unchanged (the pinned id in
      `test_cohort_id_stable` passes untouched). An explicit `"mode": "include"`,
      `"vendor": null` or `"scope": "patient"` gives the same id. `exclude` gives a different id
      from `include`, and `report` from `patient`.
- [ ] `apply` supports `set_mode` and `set_scope`. `set_mode` to a negated mode clears a pivot
      that references the criterion.
- [ ] Questions 10, 11, 14, 17 and 18 give the expected counts on the phase 2 mart (Test plan).
- [ ] Each attack test shows the leak with the rule bypassed (raw numbers) and no leak in the
      returned result.
- [ ] `suppress_count` / `suppress_pivot` raise `ValueError` when `raw.neighbours` does not
      match `neighbours(d)`.
- [ ] A definition with more than 32 neighbours is a 400 from `POST /api/cohort` naming
      `population`, and is still accepted by `POST /api/apply` and `parse`.
- [ ] `loosen_offered` is False and `loosen` is `[]` for any definition with neighbours.
- [ ] No result for a phase 2 definition contains an integer 1–4 or any `research_id` /
      `report_id` (the `walk` leak test over a phase 2 definition list).
- [ ] REST and MCP give identical JSON for the new parity cases. `web/openapi.json` matches
      `app().openapi()`.
- [ ] `mart.report` has `collected_on DATE` as its last column, equal to
      `unified.report.collected_on`.
- [ ] Discover: mode select, same-report switch, data entries, Then… / sequence card, vendor
      select, Compare and Feasibility statement work against the API. `bun run typecheck` and
      `bun test` pass.
- [ ] Docs updated per Deviations.
- [ ] `uv run pytest -q` passes. Dashboard check: n/a (no `dashboard/` code change; only
      `COHORT_DISCOVERY.md` text).

## Test plan

All tests build synthetic DuckDB files in pytest temp dirs. None reads `$DATA/raw`, the PHI file or
the real de-id file.

### `tests/test_cohort.py` (existing)

- `Mart.report(..., collected_on=None)`: stored as given, defaulting to `date(year, 6, 1)` when
  `year` is not None, else None. `write_mart` adds `collected_on DATE` as the last `mart.report`
  column (18 placeholders). `test_app.py` imports these helpers and needs no change for them.
- `test_question_1`: `r.reports == 7` becomes `r.reports is None`. The year-range neighbour
  `[2024, 2025]` has 6 matching reports (n10b is the only 2023 one), so 7 would reveal 1 report.
  Leave a comment saying so.
- `test_deferred_features_rejected`: keep only the `version 2` case and rename the test
  `test_unsupported_version_rejected`.
- `test_operations`: the `{"kind": "exclude"}` case's fragment becomes
  `"does not match any of the expected tags"`. Add `set_mode` / `set_scope` checks, an unknown id
  for `set_mode`, and `set_mode` exclude on the pivot's criterion clearing the pivot.
- `test_json_schema`: kinds gain `data` and `sequence`; ops gain `set_mode` and `set_scope`. The
  §3.1 example now parses with its `exclude` criterion
  (`{"id": "c2", "kind": "alteration", "gene": ["STK11", "KEAP1"], "mode": "exclude"}`).
- `test_static_validation` / `_definition_level`: add one case per new message (Validation).
- `test_cohort_id_stable`: add the equalities and inequalities in the acceptance criteria.

### `tests/test_cohort_phase2.py` (new)

Imports `Mart`, `write_mart`, `use_mart`, `alt`, `ihc`, `defn`, `pop`, `steps`, `cells`,
`pcells`, `margins`, `line_nones` and `walk` from `test_cohort`. A module fixture builds the
phase 2 mart below. All reports are Caris tissue, `collected_on` `YYYY-06-01`, sex female and tier
pathogenic unless stated.

| Group | Patients / reports | Facts |
|---|---|---|
| NSCLC | `l0`–`l31`, report `l{i}r` 2024. Exceptions: `l20`–`l24` have `l{i}a` (2023) and `l{i}b` (2024); `l25`–`l26` have `l{i}r` in 2025. Male: `l0`–`l2`, `l9`–`l13` | KRAS G12D on `l0`–`l19` (r), `l20`–`l24` (a), `l25`–`l26` (r); none on `l27`–`l31`. STK11 (Q37*) on `l0`–`l5` (r) and `l20`–`l24` (b). KEAP1 (G333C) on `l6`–`l8`, `l27`–`l28` (r) |
| PAAD | `q0`–`q9`, 2024 | KRAS G12D on `q0`–`q1` |
| COADREAD | `d0`–`d29`, 2023 | KRAS G12D `d0`–`d7`; NRAS Q61K `d8`–`d12`; BRAF V600E `d13`–`d17`; `tested_negative` KRAS `wildtype` on `d8`–`d24`; `tested_negative` NRAS `wildtype` on `d18`–`d22` |
| GIST | `g0`–`g29`, 2024 | KRAS G12D `g0`–`g9`; `tested_negative` KRAS `wildtype` on `g10`–`g26` (`g27`–`g29` have no KRAS result) |
| BRCA | `s0`–`s9`: tissue `s{i}t` collected 2022-03-01; liquid `s{i}l` (assay_class liquid) on 2023-05-01 for `s0`–`s6`, 2022-03-01 for `s7` (same day), 2021-05-01 for `s8`; `s9` tissue only | ESR1 Y537S on `s0l`–`s4l` and on `s5t`–`s9t` |
| MEL | `x0`–`x16`: Caris `x{i}c` 2024-02-01 and FMI `x{i}f` 2024-08-01; `y0`–`y5` Caris only 2024-02-01 | TMB (`biomarker`, key TMB, val call): Caris `low` on `x0`–`x6` and `y*`, `high` on `x7`–`x16`; FMI `low` on `x0`–`x6` and `x12`–`x16`, `high` on `x7`–`x11` |
| PRAD | `h0`–`h14`, liquid, 2024 | DNMT3A R882H `h0`–`h4`; TET2 Q810* `h5`–`h9` |
| IDC | `e0`–`e29`, 2024 | `ihc` ER (sp1) `positive` on `e0`–`e11`; PIK3CA E545K on `e0`–`e2` and `e12`–`e13` |
| ILC | `w0`–`w29`, 2024 | `ihc` ER (sp1) `positive` on `w0`–`w11`; PIK3CA E545K on `w0`–`w4` and `w12`–`w13` |
| HGSOC | `z0`–`z29`, 2024 | `ihc` ER (sp1) `positive` on `z0`–`z9`; TP53 R273H and BRCA1 E1836K both on `z0`–`z1` and `z20`–`z24` |

The PIK3CA, TP53 and BRCA1 rows outside the ER patients exist so that each gene is held by at
least 5 patients and passes the vocabulary floor.

Questions:

- `test_question_10`: population NSCLC, `c1` KRAS, `c2` STK11 or KEAP1. Include → `[32, 27, 14]`.
  `c2` exclude → `[32, 27, 13]`. Report scope include → `[32, 27, 9]`. Report scope exclude →
  `[32, 27, 18]`.
- `test_question_11`: population COADREAD, `c1` exclude KRAS/NRAS, `c2` exclude BRAF `aa`
  V600E → `[30, 17, 12]`. Adding `c3` tested_negative KRAS → `[30, 17, 12, 7]`. The
  `tested_negative` note is present. Every-gene semantics: `c1` tested_negative `["KRAS", "NRAS"]`
  alone → `[30, 5]`. "Any gene" would give 12, so this pins decision 2.
- `test_question_14`: no population, `c1` sequence first `[data tissue]` then `[data liquid]` →
  7. `by_year` is `[(2023, 7)]`. The same-day `s7` and the earlier `s8` do not count.
  `then: [ESR1, data liquid]` → 5. Population BRCA, report scope, `c1` ESR1, `c2` data liquid →
  `[10, 10, None]`: the raw 5 is 4 below patient scope's 9, so the scope rule hides it. Patient scope of the same → `[10, 10, None]` (the funnel delta rule hides 9).
- `test_question_17`: population MEL, `c1` data both_vendors, `c2` biomarker TMB vendor caris,
  `c3` biomarker TMB vendor fmi, pivot `c2.val` × `c3.val`. `count` → patients 17. `pivot` cells
  `{("low","low"): 7, ("high","high"): 5, ("high","low"): 5}`, row totals
  `{"low": 7, "high": 10}`, column totals `{"low": 12, "high": 5}`. The `both_vendors` note is
  present.
- `test_question_18`: population PRAD + assay_class liquid, `c1` DNMT3A or TET2 → `[15, 10]`;
  exclude → `[15, 5]`.

Attack tests. Each asserts the raw numbers that make the attack (from `queries._run_count` /
`_run_pivot`) and then the returned result.

- `test_attack_exclusion_complement` (A ∧ ¬B rule): population IDC, `c1` exclude PIK3CA, `c2` ER.
  Raw funnel `[30, 25, 9]`: both deltas are 5 or more, so the funnel rule alone would show 9.
  `count` of population IDC with `c1` ER alone shows 12, and 12 − 9 reveals the 3 ER patients
  with PIK3CA. The returned result is `[30, 25, None]` with `patients is None`. Control: the
  same definition on ILC (5 ER patients with PIK3CA) shows `[30, 23, 7]`.
- `test_attack_two_exclusions_together`: population HGSOC, `c1` exclude TP53, `c2` exclude
  BRCA1, `c3` ER. Raw 8. Removing `c1` or `c2` alone gives 8 (difference 0), but removing both
  gives ER alone, 10, so 2 would be revealed. The result is hidden. This pins the subset
  neighbours.
- `test_attack_exclusion_breakdown_cell`: question 10's patient-scope exclusion with breakdown
  `sex`. Raw: male 5 (`l9`–`l13`), neighbour male 8 (`l0`–`l2` and `l9`–`l13`). The result's male
  cell is None, and the line rule then hides female (8).
- `test_attack_exclusion_pivot_cell`: the same definition with pivot `sex` × `year`. The
  `("male", "2024")` cell is None, and `line_nones` holds no line with exactly one hidden value.
- `test_attack_exclude_against_tested_negative`: population GIST, `c1` KRAS. `exclude` gives raw
  `[30, 20]`, `tested_negative` gives `[30, 17]`; 20 − 17 is the 3 patients with no KRAS result.
  The `exclude` count is shown (20) and the `tested_negative` count is None. `neighbours` of the
  first is the criterion dropped; of the second, the criterion dropped and the criterion as
  `exclude`.
- `test_attack_report_scope_against_patient_scope`: population UVM (40 patients; `u0`–`u2` have two
  reports with KRAS on `a` and STK11 on `b`, `u3`–`u8` have both on one report, KRAS on `u0`–`u34`),
  `c1` KRAS, `c2` exclude STK11. Raw funnel `[40, 35, 29]` at report scope against `[40, 35, 26]` at
  patient scope; 29 − 26 = 3. The report-scope result is `[40, 35, None]` and `patients is None`,
  its last neighbour has `scope == "patient"`, the patient-scope result shows 26, and a
  report-scope definition with one include criterion has no neighbours.
- `test_attack_single_exclusion_report_vs_patient_scope`: UVM, `c1` exclude STK11. Raw `[40, 34]` at
  report scope against `[40, 31]` at patient scope; the report-scope `patients` is None and its last
  neighbour has `scope == "patient"`.
- `test_attack_union_population`: population `[NSCLC, PAAD]`, `c1` KRAS. Raw 29 against neighbour
  `[NSCLC]` 27, so 2 would be revealed. `patients is None`. `count` of `[NSCLC]` alone shows 27.
  The population alone (`[NSCLC, PAAD]`, no criteria) shows 42.
- `test_attack_union_years`: population NSCLC years `[2024, 2025]`, `c1` KRAS. Raw 22 against
  neighbour `[2024, 2024]` 20, so the result is hidden.
- `test_attack_funnel_delta_with_exclusion`: population PAAD, `c1` exclude KRAS. Raw `[10, 8]`,
  so 10 − 8 would reveal 2. The result is `[10, None]`. `_funnel([10, 8]) == [10, None]` shows
  the funnel rule hides it on its own, and the neighbour check agrees.
- `test_neighbour_check_each_value` (unit, hand-built `RawCount` / `RawPivot`): one case each for
  a funnel step, `reports`, a year, a breakdown cell, a denominator, a pivot cell, a row total and
  a column total. A difference of 0 or 5 is shown and 1–4 is hidden. An absent neighbour key
  counts as 0.
- `test_suppress_requires_neighbours`: `suppress_count(d_with_exclusion, RawCount(... no neighbours))`
  raises `ValueError`, and so does `suppress_pivot`.
- `test_neighbours`: the order and `step` maps for a definition with `c1` include, `c2` exclude,
  `c3` include, `c4` tested_negative, oncotree `[A, B]` and years `[2022, 2024]`. That gives 3
  subsets, 1 mode swap (`c4`), 2 values and 2 year ends. For `S = {c2}`, `step == [0, 1, 1, 2, 3]`. Three negated
  criteria, a year range and 24 OncoTree values make 33 neighbours → `DefinitionError` naming
  `population`, while `parse` and `data_notes` on that definition do not raise.
- `test_loosen_withheld_with_neighbours`: a small exclusion cohort gives `loosen == []` and
  `loosen_offered is False`. Question 14's sequence gives `loosen_offered is True`.
- `test_no_small_numbers_and_no_ids_phase2`: the `walk` leak test from `test_cohort.py` over
  `count` and (where a pivot is set) `pivot` of every definition above.
- `test_compile_phase2_binds_values`: compiled SQL text for exclude, tested_negative, data,
  sequence, vendor and report scope contains no caller value (gene, vendor, marker), and those
  values appear in `params`.

### `tests/test_app.py`

New `CASES`: `count` with a `c2` exclude (NSCLC, KRAS, ALK fusion exclude); `count` with
`"scope": "report"`; `count` with population `{"oncotree": ["NSCLC", "COADREAD"]}`
(`loosen_offered` false); `apply_case({"op": "set_mode", "id": "c1", "mode": "exclude"})`; and
`apply_case({"op": "set_scope", "scope": "report"})`. A new test checks that a definition with 33
neighbours is a 400 whose detail starts with `population:` on REST, and a tool error on MCP.
`test_openapi_snapshot` passes after `bun run gen`.

### `tests/test_pipeline.py`

`REPORT_COLS` gains `("collected_on", "DATE")` last. In `test_mart_report_rows`, the
`IS DISTINCT FROM` query also checks `m.collected_on IS DISTINCT FROM u.collected_on`.

### Web (`bun test`)

- `cohort.test.ts`: `criterionLabel` for exclude, tested_negative, `data`, `sequence` and vendor;
  `newCriterion` for `data.has`; `dataEntries("liquid")`; `modesFor` for alteration with and
  without `aa`, `ihc` and `sequence`; `pivotAxes` skips negated, `data` and `sequence` criteria.
  `feasibility`: with `patients: null` it says "a suppressed number" and never "fewer than", and the
  closing sentence names `r.min_cell`. Every digit run in the statement is
  a number in `r` (formatted), a year in `years`, a cut point in the definition or the
  `toFixed(1)` accrual figure. With no criteria there is no "of whom" clause.
- `answer.test.tsx`: `loosen_offered: false` with `patients: null` renders the subtraction
  message and not "No single criterion".
- `builder.test.tsx`: an alteration card renders three mode options and an `ihc` card two. The
  same-report checkbox is checked for `scope: "report"`. A sequence card renders both member
  lists.
- `compare.test.tsx` (new): `CompareTable` with two columns renders "<5" and its legend for a null count, one row
  per year in the union of the years, and each column's `cohort_id` as the header `title`.
- `builder.test.tsx`: `withoutMember` (the any_of card's remove-member step) keeps the mode of
  an excluded `any_of` on the member left, so removing a member never turns an exclusion into an
  include.

### Commands

```bash
uv run pytest -q
(cd web && bun install --frozen-lockfile && bun run typecheck && bun test)
```

Dashboard check: n/a (no change under `dashboard/` other than `COHORT_DISCOVERY.md`).

## Risks

- **Differencing beyond one edit.** The neighbour check closes two-query attacks one edit away.
  These stay open and are accepted under the audit log and the rate limit, like phase 1's
  cross-query differencing:
  - Combinations of three or more queries, for example
    `[(A∧¬B over {X,Y}) − (A∧¬B over {X})]` against the same pair without the exclusion.
  - OR lists inside a criterion (decision 1's scope).
  - The mirror case: A and A ∧ B are both phase 1 queries, so A ∧ ¬B was already computable before
    #38.

  `COHORT_ROUND=5` is the existing lever if this proves too weak. Say so in §3.6.
- **Fewer answers.** The neighbour check hides some counts that are not small, such as question 1's
  report count. Union cohorts lose loosen suggestions. The data note explains both. Watch for
  complaints before widening anything.
- **Cost.** Up to 33 statements per count or pivot. On the synthetic mart one statement takes about
  20 ms. If the real mart is much slower, lower `MAX_NEIGHBOURS`, which is a constant.
- **FMI under-reports tested-negative** (pertinent negatives only) and **cross-vendor linkage is
  partial** (FMI reports without an MRN fall back to name and birth date). Both are stated in data
  notes. `both_vendors` and question 17 are lower bounds.
- **Date shift and sequence.** The order relies on one shift offset per patient, which `deid`
  guarantees for reports that share a patient key. Reports split across patient keys never share a
  `research_id`, so they are never compared.
- **Schema change to `mart.report`.** Adding the last column changes `test_pipeline`'s column
  list. `pop` always selects `collected_on`, so every `count` / `pivot` fails against a de-id
  file whose mart was built before this change, until the daily rebuild writes the new mart.
  The app runs only on the dev tailnet, and nothing else reads the mart. The PR description
  says so; no compatibility code.
- **Seam blast radius.** `suppress.py` and `compile.py` are the seam every surface sits on. The
  `ValueError` guard makes a missing neighbour check fail loudly rather than leak. The parity test
  and the leak walk run over the new shapes.
