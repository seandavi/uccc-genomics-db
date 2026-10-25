# Spec #34: cohort module — definition, operations, cohort_id, compile, suppress

Part of #23, phase 1 of `dashboard/COHORT_DISCOVERY.md` (§3.1, §3.5, §3.6, §4);
`docs/ARCHITECTURE.md` decisions 1–2. Builds on #33 (`mart.report`, `mart.fact`; spec
`docs/specs/33-mart-schema-mart-report-and-mart-fact.md`). Labels: `seam`, `review:security`.
This is the deep module that REST, MCP and the chat will be thin layers over.

All examples and fixture values are synthetic. Gene symbols, OncoTree codes, IHC marker names
and calls are public vocabulary, not patient data. No real counts appear.

## Goal

A Python package `uccc_genomics_mcp.cohort` that:

1. defines the **cohort definition** (Pydantic v2, versioned, JSON Schema exported) and
   normalises it during validation;
2. hashes it into a stable **`cohort_id`**;
3. edits it only through **operations** (`apply(definition, op) -> definition`);
4. loads a floored **vocabulary** from the mart, with `search(q)` for typeahead;
5. **compiles** a definition to `(sql, params)` over `mart.*`, with values only as bound
   parameters;
6. runs **`count`** and **`pivot`** and returns typed results, each of which has passed
   **suppression**: the floor of 5, secondary suppression (on both axes for pivots), floored
   funnel deltas and the whole-cohort rule.

Done when the module answers questions 1–9, 12, 13, 15, 16 and 20 (include-only) on a synthetic
mart, and the suppression tests pass.

## Non-goals

- No HTTP route, MCP tool, React page or chat. `cohort_api.py` keeps serving the public
  dashboard unchanged. The only change there is importing `MIN_CELL` and `floor` from the new
  module so the floor has one definition.
- No `exclude` / `tested_negative` modes, no `scope: "report"`, no `sequence` or `data` kinds
  (phase 2, `COHORT_DISCOVERY.md` §4 and open question 3). They are rejected with a clear error.
- No "criterion matched: yes/no" pivot axis. Its "no" side is a complement (A ∧ ¬B), which is
  the exclusion decision still waiting on open question 3.
- No "widen" loosen suggestions (next coarser vocabulary value). Phase 1 offers only "drop".
- No audit log, rate limit or auth. Those belong to the REST/MCP layers (ARCHITECTURE
  decisions 8 and 11), which call this module.
- No Postgres, no saved versions. `apply` returns a new immutable definition; storing versions is
  the caller's job.
- No change to `deid.py`, `mart.sql`, id hashing or date shifting. `research_id` and `report_id`
  are only read, inside SQL, and never returned.
- No new third-party dependency. Pydantic is already installed (a dependency of `mcp`, locked at
  2.13.5). It becomes a **declared** direct dependency of the `mcp/` member, because the module
  imports it and ARCHITECTURE decision 1 names it.

## Deviations from the issue and design docs (the implementer updates the docs in the same PR)

1. **Location** (the issue leaves it to the spec): `mcp/src/uccc_genomics_mcp/cohort/`. It sits
   next to `server.py`, whose hardened connection it uses, and next to the future FastAPI
   service.
2. **New criterion kind `any_of`**: OR across modalities. Questions 4, 6 and 7 need "MSI-high
   **or** TMB ≥ 10", "HER2-low IHC **or** ERBB2 amplification" and "HRR variant **or**
   LOH-high". §2 says such a rule is "one eligibility criterion that spans two tables", but
   §3.1's kinds cannot express it. `any_of` holds 2–8 leaf criteria and counts as one criterion
   (one funnel step). Add a row to the §3.1 kinds table.
3. **Population fields**: `age` becomes `age_band`, the `mart.report` column, so the concept
   has one spelling. `organ` is added because the mart has it and the phase 1 API filters on it.
4. **`ihc.measure`** takes the mart's `unit` spelling: `TPS` or `CPS`, not `tps`. `% stained`
   has no cut points in §3.1, so it is not a measure.
5. **`expression.gene` is a list** (values OR), consistent with `alteration.gene`. §3.1 has a
   single `gene`.
6. **Breakdown dimensions** are `oncotree`, `organ`, `sex`, `age_band`, `vendor`,
   `assay_class`, `site_type` and `has_wts`. `by_year` is always returned, so `year` is not a
   breakdown. There is no `vendor_class`: a `vendor` × `assay_class` pivot covers it. Update the
   §3.1 example.
7. **Pivot axes** are a dimension (the breakdown dimensions plus `year`), or `c<n>.key`,
   `c<n>.sub` or `c<n>.val`: the matched fact's column for criterion `c<n>`. There is no yes/no
   criterion axis (see Non-goals). Question 9's "CLDN18+ only" and "neither" cells therefore wait
   for exclusion. Its include-only counts (both stains, CLDN18+, CPS ≥ 10, both) come from the
   funnel. A `sub` or `val` axis carries vendor free text (protein change, fusion partner,
   therapy name, trial id, IHC clone), which the vocabulary floor keeps out of the typeahead.
   A pivot label held by fewer than 5 cohort patients is therefore folded into one `other`
   label in SQL before counting. A `key` axis is a value the caller chose from the vocabulary
   and is not folded.
8. **Question 16's RNA part** comes from the `has_wts` breakdown, because the `data` kind is
   phase 2.
9. **A criterion with no value filter means "has any result of this kind"**: an `ihc` without
   `call` or `at_least`, a `biomarker` without `call` or `at_least`, an `expression` without
   `percentile_at_least`. This is how a caller restricts the cohort to patients who were tested,
   so the percentage is honest (§3.4's "restrict to Caris-tested patients"; questions 8 and 9).
10. **`cohort_id` covers what selects patients**: `version`, `population`, `scope` and the
    criteria. It does not cover `name`, `breakdown`, `pivot`, criterion ids or criterion order.
    A rename or a new breakdown is a new version of the same cohort.
11. **Patient scope, made precise.** §3.1 says criteria "match on any of the patient's reports".
    Here that means any of the patient's **in-population** reports, the ones passing the
    population filters, as the phase 1 API does today. Without this, `vendor` or `years` would
    not constrain the findings. The accrual year is the year the patient first met **every**
    criterion: for each criterion, the earliest year among the in-population reports that match
    it, and then the latest of those years.
12. **Loosen suggestions are delta-floored.** A suggestion is shown only if its count is at
    least 5, at least 5 above the current cohort's raw count, **and** consistent with the whole
    funnel: it is not 1..4 away from a shown funnel step and does not equal a step the funnel
    rule hid. A suggestion is a set nested in every earlier funnel step, so without these tests
    it can reveal a count the funnel delta rule hid (worked examples under Suppression).
13. **Breakdown cell versus denominator is not delta-floored.** A cell is nested in its
    population denominator, so the two shown together differ by the patients with that value who
    miss the criteria. Questions 4 and 20 are exactly that ratio (8 of 10, 6 of 10), so hiding
    it would remove the answer. It is accepted under the audit log like differencing across
    queries (§3.6 of `COHORT_DISCOVERY.md`). Everything else in one result (a list, a pivot, the
    funnel, the loosen suggestions) is closed under subtraction.
14. **The vocabulary shows `patients` only for entries without a parent.** A parent's count
    minus the sum of its shown children would recover the floored-out children (a marker's
    count minus its shown calls). Children (`alteration.aa`, `biomarker.call`, `ihc.clone`,
    `ihc.call`) carry `patients = None`; they are offered, validated and ranked alphabetically.

Docs to update: `COHORT_DISCOVERY.md` §3.1 needs a short "Phase 1 (#34)" paragraph listing
items 2–9 and 11, the `any_of` row, and the example JSON with `age_band`, `"measure": "TPS"`,
`breakdown: ["oncotree", "has_wts"]`, and the `exclude` criterion marked phase 2. §3.3's
loosen bullet takes item 12. §3.6 takes items 13 and 14 and the pivot label fold. ARCHITECTURE decision 1 gets one sentence naming the package path.
README Layout gets a `cohort/` line, and `mart.*` "Nothing reads it yet" becomes "read by the
cohort module". AGENTS.md Layout gets a `cohort/` line.

## Design

### Files

| file | change |
|---|---|
| `mcp/src/uccc_genomics_mcp/cohort/__init__.py` | **new**: the public surface (re-exports, below) |
| `mcp/src/uccc_genomics_mcp/cohort/definition.py` | **new**: models, constants, validation and normalisation, `parse`, `cohort_id`, `json_schema`, operations and `apply`, `data_notes` |
| `mcp/src/uccc_genomics_mcp/cohort/vocabulary.py` | **new**: `VocabEntry`, `Vocabulary` (`.allowed`, `.check`, `.search`), `VOCAB_SQL` |
| `mcp/src/uccc_genomics_mcp/cohort/compile.py` | **new**: `compile(d)`, `compile_pivot(d)` |
| `mcp/src/uccc_genomics_mcp/cohort/suppress.py` | **new**: `MIN_CELL`, `ROUND`, `floor`, result models, raw dataclasses, `suppress_count`, `suppress_pivot` |
| `mcp/src/uccc_genomics_mcp/cohort/queries.py` | **new**: `vocabulary()`, `count(d)`, `pivot(d)`. The only code that opens a connection |
| `mcp/src/uccc_genomics_mcp/cohort_api.py` | delete its own `MIN_CELL`, `ROUND` and `floor`; `from uccc_genomics_mcp.cohort.suppress import MIN_CELL, floor`. No behaviour change |
| `mcp/pyproject.toml` | add `"pydantic>=2.11"` to `dependencies` (the `validate_by_name` / `serialize_by_alias` config keys arrived in 2.11) |
| `uv.lock` | regenerated with `uv lock` (CI runs `uv sync --locked`) |
| `tests/test_cohort.py` | **new** (test plan below) |
| `tests/conftest.py` | add `deid_lacks_mart()`, next to `deid_lacks_tier()` |
| `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `dashboard/COHORT_DISCOVERY.md` | per Deviations |

`__init__.py` exports exactly:

```python
from .definition import (CUT_POINTS, SCHEMA_VERSION, Definition, DefinitionError, Population,
                         apply, cohort_id, data_notes, json_schema, operation_json_schema, parse)
from .queries import count, pivot, vocabulary
from .suppress import MIN_CELL, CountResult, PivotResult
from .vocabulary import VocabEntry, Vocabulary
```

### `definition.py`

Every model uses
`ConfigDict(extra="forbid", frozen=True, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)`.
Normalisation happens in `field_validator`s, so **every constructed `Definition` is already
normalised**. There is no separate `normalise()` call to forget.

Constants:

```python
SCHEMA_VERSION = 1
POP_DIMS = ("oncotree", "organ", "sex", "age_band", "vendor", "assay_class")   # = mart.report columns
BREAKDOWN_DIMS = POP_DIMS + ("site_type", "has_wts")
PIVOT_DIMS = BREAKDOWN_DIMS + ("year",)
TIERS = ("pathogenic", "likely_pathogenic", "vus", "unclassified")        # benign is never an alteration (#32)
DEFAULT_TIERS = ["likely_pathogenic", "pathogenic"]
ALT_CLASSES = ("mutation", "amplification", "loss", "fusion")
EVIDENCE = ("caris_level1", "fmi_fda_any_indication", "fmi_trial")
# COHORT_DISCOVERY.md §3.1 fixed cut points (open question 4); no free numbers.
CUT_POINTS = {"biomarker.TMB": [10.0, 16.0, 20.0], "ihc.TPS": [1.0, 50.0], "ihc.CPS": [1.0, 10.0, 20.0],
              "expression.percentile": [50.0, 75.0, 90.0], "specimen.purity": [20.0, 30.0, 50.0]}
DEFERRED_KINDS = ("sequence", "data", "tested_negative", "exclude")
```

`class DefinitionError(ValueError)` is the one error type for callers (REST maps it to 400).
Its message is `"<loc>: <msg>"`, built from the first Pydantic error (`".".join(map(str, loc))`)
or written directly.

#### Models

```python
class Population(BaseModel):
    oncotree: list[str] = Field(default=[], max_length=100)
    organ: list[str] = Field(default=[], max_length=100)
    sex: list[str] = Field(default=[], max_length=10)
    age_band: list[str] = Field(default=[], max_length=10)
    vendor: list[str] = Field(default=[], max_length=10)
    assay_class: list[str] = Field(default=[], max_length=10)
    years: tuple[int, int] | None = None            # inclusive [from, to]; from <= to

class _Criterion(BaseModel):
    id: str | None = None                           # required at the top level, absent in any_of members
    mode: Literal["include"] = "include"            # exclude / tested_negative: phase 2

class Alteration(_Criterion):
    kind: Literal["alteration"]
    gene: list[str] = Field(min_length=1, max_length=100)
    class_: list[Literal[ALT_CLASSES]] = Field(default=[], alias="class")   # [] = any class
    aa: list[str] = Field(default=[], max_length=50)                         # needs exactly one gene
    tier: list[Literal[TIERS]] = []                                          # [] -> DEFAULT_TIERS

class Biomarker(_Criterion):
    kind: Literal["biomarker"]
    name: Literal["TMB", "MSI", "LOH"]
    call: list[str] = Field(default=[], max_length=10)
    at_least: float | None = None                   # TMB only, from CUT_POINTS["biomarker.TMB"]

class Ihc(_Criterion):
    kind: Literal["ihc"]
    marker: str
    clone: str | None = None
    call: list[str] = Field(default=[], max_length=20)
    measure: Literal["TPS", "CPS"] | None = None
    at_least: float | None = None                   # needs measure; from CUT_POINTS[f"ihc.{measure}"]

class Expression(_Criterion):
    kind: Literal["expression"]
    gene: list[str] = Field(min_length=1, max_length=20)
    percentile_at_least: float | None = None        # CUT_POINTS["expression.percentile"]

class Specimen(_Criterion):
    kind: Literal["specimen"]
    site_type: list[str] = Field(default=[], max_length=20)
    site: list[str] = Field(default=[], max_length=50)
    purity_at_least: float | None = None            # CUT_POINTS["specimen.purity"]

class Actionability(_Criterion):
    kind: Literal["actionability"]
    evidence: list[Literal[EVIDENCE]] = Field(min_length=1)

Leaf = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability, Field(discriminator="kind")]

class AnyOf(_Criterion):
    kind: Literal["any_of"]
    of: list[Leaf] = Field(min_length=2, max_length=8)

Criterion = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability | AnyOf,
                      Field(discriminator="kind")]

class Pivot(BaseModel):
    rows: str
    cols: str

class Definition(BaseModel):
    version: Literal[1] = 1
    name: str = Field(default="", max_length=200)
    population: Population = Population()
    criteria: list[Criterion] = Field(default=[], max_length=10)
    scope: Literal["patient"] = "patient"
    breakdown: list[Literal[BREAKDOWN_DIMS]] = Field(default=[], max_length=4)
    pivot: Pivot | None = None
```

(`Literal[ALT_CLASSES]` stands for the literal of those strings. Write them out, or use
`Literal[*ALT_CLASSES]` on Python 3.12, whichever pyright accepts.)

#### Validation and normalisation rules (validators; each failure raises with a message naming the field)

- **String lists** (every `list[str]` above): strip each value, reject empty strings, dedupe,
  sort ascending.
- **Genes** (`Alteration.gene`, `Expression.gene`): additionally `.upper()`. **Calls**
  (`Biomarker.call`, `Ihc.call`), `Ihc.clone`, `Specimen.site_type` and `Specimen.site`:
  additionally `.lower()`, because the mart stores `call_norm`, clone and site in lower case.
  `Ihc.marker` and `aa` keep their case: protein changes such as `E746_A750del` are
  case-sensitive.
- **Literal lists** (`class`, `tier`, `evidence`, `breakdown` aside): dedupe and sort. `class`
  equal to all four classes normalises to `[]`. `tier == []` normalises to `DEFAULT_TIERS`.
- `Alteration.aa` non-empty → `len(gene) == 1`, and `class` must be `[]` or `["mutation"]`.
  It normalises to `["mutation"]`.
- `Biomarker`: `call` and `at_least` are mutually exclusive. `at_least` is allowed only for
  `TMB` and must be in `CUT_POINTS["biomarker.TMB"]`.
- `Ihc`: `call` excludes `measure`/`at_least`. `at_least` needs `measure` and must be in
  `CUT_POINTS[f"ihc.{measure}"]`. `measure` alone means "has a score in that unit".
- `Expression.percentile_at_least` and `Specimen.purity_at_least` must be in their
  `CUT_POINTS` list.
- `Specimen` needs at least one of `site_type`, `site`, `purity_at_least`.
- **Deferred features** have a clear message, checked in `mode="before"` validators so the
  message wins over Pydantic's generic discriminator error:
  - `Definition.criteria` and `AnyOf.of`: a raw item whose `kind` is in `DEFERRED_KINDS` gives
    `"criterion kind '<kind>' is not supported yet"`. A raw `mode` other than
    `None`/`"include"` gives `"criterion mode '<mode>' is not supported yet; criteria are include-only"`.
  - `Definition.scope == "report"` gives
    `"scope 'report' is not supported yet; criteria match on any of the patient's in-population reports"`.
  - Any `version` other than 1 gives `"unsupported definition version <v>"`.
- `Population.years`: `from <= to`. The range against the data is checked by the vocabulary.
- `Definition` `model_validator(mode="after")`:
  - every top-level criterion has an `id` matching `^c[1-9][0-9]{0,2}$`, and ids are unique;
  - every `any_of` member has `id is None`;
  - `breakdown` has no duplicates;
  - `pivot`: `rows != cols`. Each axis is in `PIVOT_DIMS` or matches
    `^(c[1-9][0-9]{0,2})\.(key|sub|val)$` with that id present. A criterion axis may not
    reference a `specimen` criterion or an `any_of` containing one: specimen facts are split
    across keys, so "the matched fact" is undefined.

#### Functions

```python
def parse(data: dict) -> Definition
    """Definition.model_validate(data), with ValidationError re-raised as DefinitionError."""

def cohort_id(d: Definition) -> str
    """f"v{SCHEMA_VERSION}-{sha256(canonical).hexdigest()[:16]}" where canonical =
    json.dumps({"version": d.version, "scope": d.scope,
                "population": d.population.model_dump(mode="json", exclude_defaults=True),
                "criteria": sorted((_canon(c) for c in d.criteria), key=lambda c: json.dumps(c, sort_keys=True))},
               sort_keys=True, separators=(",", ":"))
    _canon(c) = c.model_dump(mode="json", by_alias=True, exclude_defaults=True, exclude={"id"})."""
```

`exclude_defaults=True` keeps existing ids stable when a later version adds an optional field.
`AnyOf.of` is sorted by `json.dumps(member_dump, sort_keys=True)` in its validator, so member
order never changes the id either. The `v1-` prefix keeps a `cohort_id` from looking like a
16-hex `research_id`.

```python
def json_schema() -> dict             # Definition.model_json_schema(by_alias=True)
def operation_json_schema() -> dict   # TypeAdapter(Operation).json_schema(by_alias=True)
def data_notes(d: Definition) -> list[str]
```

`data_notes` is a pure function of the definition. It returns the triggered entries of `NOTES`
in this order, then always `NOTES["absent"]`:

| key | triggered by | text |
|---|---|---|
| `age` | `population.age_band` non-empty, `"age_band"` in breakdown, or a pivot axis `age_band` | `Age is known for Caris tissue reports only; everything else is 'unknown'.` |
| `ihc` | any `ihc` criterion (including inside `any_of`) | `IHC results are Caris only, so FMI patients cannot match an IHC criterion.` |
| `expression` | any `expression` criterion | `Expression percentiles come from Caris whole-transcriptome reports only.` |
| `specimen` | a `specimen` criterion with `site_type` or `site`, `"site_type"` in breakdown, or a pivot axis `site_type` | `Specimen site and type are Caris only, from the report's first tumor specimen.` |
| `has_wts` | `"has_wts"` in breakdown or a pivot axis `has_wts` | `has_wts is Caris only; FMI reports are always 'false'.` |
| `fda` | `fmi_fda_any_indication` in any `actionability.evidence` | `FMI's FDA flag means approved in any indication, not necessarily in this tumor type.` |
| `absent` | always | `Stage, treatment, outcomes, race and ethnicity are not in this data.` |

#### Operations

Each operation is a model discriminated on `op`:

```python
class AddCriterion(BaseModel):    op: Literal["add_criterion"]; criterion: Criterion
class RemoveCriterion(BaseModel): op: Literal["remove_criterion"]; id: str
class UpdateCriterion(BaseModel): op: Literal["update_criterion"]; id: str; criterion: Criterion
class SetPopulation(BaseModel):   op: Literal["set_population"]; population: Population
class SetBreakdown(BaseModel):    op: Literal["set_breakdown"]; breakdown: list[Literal[BREAKDOWN_DIMS]]
class SetPivot(BaseModel):        op: Literal["set_pivot"]; pivot: Pivot | None
class Rename(BaseModel):          op: Literal["rename"]; name: str
Operation = Annotated[AddCriterion | RemoveCriterion | UpdateCriterion | SetPopulation | SetBreakdown
                      | SetPivot | Rename, Field(discriminator="op")]

def apply(d: Definition, op: Operation | dict, vocab: Vocabulary | None = None) -> Definition
```

`apply` validates a `dict` op with `TypeAdapter(Operation)`. It then edits
`data = d.model_dump(mode="json", by_alias=True)` and returns `Definition.model_validate(data)`
(never `model_copy`, which skips validation). If `vocab` is given, it calls `vocab.check(new)`.
Any failure raises `DefinitionError`. `d` itself is never changed.

- `add_criterion`: appended (criterion order is funnel order). A missing `id` gets
  `c{max(existing numeric ids, default 0) + 1}`. An `id` already present is an error.
- `remove_criterion`: an unknown id is an error. If `pivot` references the id, `pivot`
  becomes `None`.
- `update_criterion`: full replacement at the same position. The id is forced to the op's
  `id`, and an unknown id is an error.
- `set_population`, `set_breakdown`, `set_pivot`, `rename`: replace that field.

### `vocabulary.py`

```python
class VocabEntry(BaseModel):
    field: str            # e.g. "population.oncotree", "alteration.aa"
    parent: str | None    # alteration.aa -> gene; biomarker.call -> name; ihc.clone/ihc.call -> marker
    value: str
    patients: int | None  # floor()ed, >= MIN_CELL; None when parent is set (deviation 14)

class Vocabulary(BaseModel):
    entries: list[VocabEntry]
    years: tuple[int, int] | None          # min/max mart.report.year; None on an empty mart
    cut_points: dict[str, list[float]] = CUT_POINTS
    min_cell: int = MIN_CELL

    def allowed(self, field: str, parent: str | None = None) -> set[str]
    def check(self, d: Definition) -> None           # DefinitionError naming the first bad value
    def search(self, q: str, limit: int = 20) -> list[VocabEntry]
```

`VOCAB_SQL` is one statement over `mart.*`. The outer `WHERE patients >= {MIN_CELL}` is the
floor: a value under 5 patients is never offered, so it cannot be OR-ed into a larger value
and recovered by differencing (the `cohort_api.VOCAB_SQL` rule). `f` is `mart.fact` without
benign mutation rows (`NOT (kind = 'alteration' AND sub = 'mutation' AND tier = 'likely_benign_or_benign')`).

| field | parent | value | source |
|---|---|---|---|
| `population.<d>` for each d in `POP_DIMS` | NULL | `d` | `mart.report`, non-NULL |
| `alteration.gene` | NULL | `upper(key)` | `f` where `kind = 'alteration'` |
| `alteration.aa` | `upper(key)` | `val` | `f` where `kind = 'alteration' AND sub = 'mutation' AND val IS NOT NULL` |
| `biomarker.call` | `key` | `val` | `f` where `kind = 'biomarker' AND val IS NOT NULL` |
| `ihc.marker` | NULL | `key` | `f` where `kind = 'ihc'` |
| `ihc.clone` | `key` | `sub` | `f` where `kind = 'ihc' AND sub IS NOT NULL` |
| `ihc.call` | `key` | `val` | `f` where `kind = 'ihc' AND val IS NOT NULL` |
| `expression.gene` | NULL | `upper(key)` | `f` where `kind = 'expression'` |
| `specimen.site_type` | NULL | `val` | `f` where `kind = 'specimen' AND key = 'site_type'` |
| `specimen.site` | NULL | `val` | `f` where `kind = 'specimen' AND key = 'site'` |
| `actionability.evidence` | NULL | `key` | `f` where `kind = 'actionability'` |

`patients` is `count(DISTINCT research_id)`, passed through `floor()` when building entries.
`years` comes from `SELECT min(year), max(year) FROM mart.report`. The floor also keeps rare
vendor free text (`specimen.site`) out of the vocabulary.

`check(d)` requires every population list to be ⊆ `allowed("population.<d>")` and `years`
within `self.years`. Per criterion, including `any_of` members:

- `alteration`: `gene` ⊆ `alteration.gene`; `aa` ⊆ `allowed("alteration.aa", gene[0])`.
- `biomarker`: `call` ⊆ `allowed("biomarker.call", name)`.
- `ihc`: `marker` ∈ `ihc.marker`; `clone` ∈ `allowed("ihc.clone", marker)`; `call` ⊆
  `allowed("ihc.call", marker)`.
- `expression`: `gene` ⊆ `expression.gene`.
- `specimen`: `site_type` and `site` ⊆ their fields.
- `actionability`: `evidence` ⊆ `actionability.evidence`.

The message names the field path and the value, e.g.
`criteria.c2.aa: 'G13D' is not in the vocabulary for KRAS`.

`search(q, limit)`: `q.strip().lower()`. An empty `q` or one longer than 100 characters gives
`[]`. `limit` is clamped to 1..50. An entry matches when `q` is a substring of
`value.lower()`. Order: exact match, then prefix match, then substring, then `patients`
descending, then `value`. Entries with a parent have no `patients` and rank as 0, so they come
alphabetically within their tier.

### `compile.py`

```python
def compile(d: Definition) -> tuple[str, dict]          # the count statement
def compile_pivot(d: Definition) -> tuple[str, dict]    # requires d.pivot; DefinitionError otherwise
```

Parameters are DuckDB named parameters (`$name`, bound from the dict, as in `cohort_api`).
Names come from code, never from the caller: population `pop_<field>`, `pop_year_from`,
`pop_year_to`; criterion `i` (0-based position) uses prefix `k{i}`, and `any_of` member `j` uses
`k{i}m{j}`. CTE names are `m{i}`/`q{i}`. Every caller value enters only through the dict.
Clauses for empty lists and `None` numbers are left out, never bound as NULL. The names that do
go into the SQL text (breakdown dimensions, pivot dimension axes, the fact column of a
criterion axis) are checked inside `compile`/`compile_pivot` against `BREAKDOWN_DIMS` /
`PIVOT_DIMS` / `AXIS_RE`, raising `DefinitionError`, so a `Definition` built or copied without
validation (`model_construct`, `model_copy(update=...)`) cannot inject SQL.

Shared CTEs (`_ctes(d) -> (sql, params)`):

```sql
WITH pop AS (            -- in-population reports
  SELECT research_id, vendor, report_id, year, year_complete, oncotree, organ, sex, age_band,
         assay_class, site_type, has_wts
  FROM mart.report
  WHERE true
    AND list_contains($pop_oncotree, oncotree)              -- one line per non-empty POP_DIMS list
    AND year BETWEEN $pop_year_from AND $pop_year_to        -- when years is set
),
pp AS (SELECT research_id, min(year) AS yr FROM pop GROUP BY research_id),     -- population patients
m0 AS (SELECT p.research_id, p.vendor, p.report_id, p.year FROM pop p WHERE <pred_0>),
q0 AS (SELECT research_id, min(year) AS yr FROM m0 GROUP BY research_id),     -- first year c1 matched
...                                                                            -- one m/q pair per criterion
cohort AS (SELECT pp.research_id, greatest(q0.yr, q1.yr, ...) AS yr           -- the year all criteria were met
           FROM pp JOIN q0 USING (research_id) JOIN q1 USING (research_id) ...),
hit AS (SELECT p.* FROM pop p JOIN cohort USING (research_id)                  -- cohort reports matching >= 1 criterion
        WHERE EXISTS (SELECT 1 FROM m0 WHERE m0.vendor = p.vendor AND m0.report_id = p.report_id)
           OR EXISTS (SELECT 1 FROM m1 WHERE ...) ...)
```

With no criteria, `cohort AS (SELECT research_id, yr FROM pp)` and `hit AS (SELECT * FROM pop)`.
DuckDB's `greatest` skips NULLs and takes one argument (both checked on 1.5.5).

`pred_i` is a predicate on `p`. For every leaf except `specimen`:
`EXISTS (SELECT 1 FROM mart.fact f WHERE f.vendor = p.vendor AND f.report_id = p.report_id AND <cond>)`.
For `specimen`, it is the AND of one such `EXISTS` per field that is set. For `any_of`, it is
`(pred_m0 OR pred_m1 ...)`. `<cond>` (`fact_cond`) for each leaf, with `P` the parameter prefix:

| kind | `fact_cond` (bracketed parts only when the field is set) |
|---|---|
| alteration | `f.kind = 'alteration' AND list_contains($P_gene, upper(f.key))` [`AND list_contains($P_class, f.sub)`] [`AND f.sub = 'mutation' AND list_contains($P_aa, f.val)`] `AND (f.sub <> 'mutation' OR list_contains($P_tier, f.tier))` |
| biomarker | `f.kind = 'biomarker' AND f.key = $P_name` [`AND list_contains($P_call, f.val)`] [`AND f.num >= $P_at_least`] |
| ihc | `f.kind = 'ihc' AND f.key = $P_marker` [`AND f.sub = $P_clone`] [`AND list_contains($P_call, f.val)`] [`AND f.unit = $P_measure`] [`AND f.num >= $P_at_least`] |
| expression | `f.kind = 'expression' AND list_contains($P_gene, upper(f.key))` [`AND f.num >= $P_pct`] |
| actionability | `f.kind = 'actionability' AND list_contains($P_evidence, f.key)` |
| specimen (per field) | `f.kind = 'specimen' AND f.key = 'site_type' AND list_contains($P_site_type, f.val)`; `... f.key = 'site' AND list_contains($P_site, f.val)`; `... f.key = 'purity' AND f.num >= $P_purity` |

The tier clause is always present on alteration (`tier` is never empty after normalisation),
so benign mutation rows, which the mart keeps, never count. `upper(f.key)` matches the
upper-cased genes against any vendor casing (`C11orf30`).

**Count statement** (`compile`): `_ctes` followed by one `SELECT` returning
`(section VARCHAR, dim VARCHAR, value VARCHAR, patients BIGINT, flag BOOLEAN)`:

```sql
SELECT 'funnel' AS section, '0' AS dim, NULL::VARCHAR AS value, (SELECT count(*) FROM pp) AS patients, NULL::BOOLEAN AS flag
UNION ALL SELECT 'funnel', '1', NULL, (SELECT count(*) FROM pp JOIN q0 USING (research_id)), NULL
UNION ALL SELECT 'funnel', '2', NULL, (SELECT count(*) FROM pp JOIN q0 USING (research_id) JOIN q1 USING (research_id)), NULL
-- ... one row per criterion
UNION ALL SELECT 'reports', NULL, NULL, (SELECT count(*) FROM hit), NULL
UNION ALL SELECT 'year', NULL, yr::VARCHAR, count(*), NULL FROM cohort WHERE yr IS NOT NULL GROUP BY yr
UNION ALL SELECT 'year_complete', NULL, year::VARCHAR, NULL, bool_and(year_complete) FROM pop WHERE year IS NOT NULL GROUP BY year
-- per breakdown dim d:
UNION ALL SELECT 'breakdown', 'd', coalesce(d::VARCHAR, 'unknown'), count(DISTINCT research_id), NULL FROM hit GROUP BY 3
UNION ALL SELECT 'denominator', 'd', coalesce(d::VARCHAR, 'unknown'), count(DISTINCT research_id), NULL FROM pop GROUP BY 3
```

**Pivot statement** (`compile_pivot`): `_ctes`, then `pv0` holding `(research_id, rv, cv)`, built
from the axes:

- dimension axis `x`: `SELECT DISTINCT research_id, vendor, report_id, coalesce(x::VARCHAR, 'unknown') AS v FROM hit`
- criterion axis `c<n>.F` (criterion at position `i`, F ∈ key/sub/val):
  `SELECT DISTINCT h.research_id, h.vendor, h.report_id, coalesce(f.F, 'unknown') AS v FROM hit h JOIN mart.fact f ON f.vendor = h.vendor AND f.report_id = h.report_id WHERE <fact_cond_i>`.
  For `any_of`, `fact_cond_i` is the OR of its members' `fact_cond`s. It reuses the same
  parameter names.

How `pv0` pairs the axes (CTEs `ra`, `ca` hold the two axis scans where needed):

| axes | `pv0` |
|---|---|
| both on the same criterion (e.g. `c1.key` × `c1.sub`) | one scan pairing on the **same fact row**: `SELECT DISTINCT h.research_id, coalesce(f.Fr,'unknown') AS rv, coalesce(f.Fc,'unknown') AS cv FROM hit h JOIN mart.fact f ON … WHERE <fact_cond_i>` |
| at least one dimension | same **report**: `SELECT ra.research_id, ra.v AS rv, ca.v AS cv FROM ra JOIN ca ON ca.vendor = ra.vendor AND ca.report_id = ra.report_id` |
| two different criteria | same **patient**: `… FROM ra JOIN ca ON ca.research_id = ra.research_id` |

`pv` maps each criterion axis whose column is `sub` or `val` through
`CASE WHEN x IN (SELECT x FROM pv0 GROUP BY x HAVING count(DISTINCT research_id) >= 5) THEN x ELSE 'other' END`
(deviation 7). Dimension axes and `key` axes pass through. Then:

```sql
SELECT 'cell' AS section, rv AS r, cv AS c, count(DISTINCT research_id) AS patients FROM pv GROUP BY rv, cv
UNION ALL SELECT 'row', rv, NULL, count(DISTINCT research_id) FROM pv GROUP BY rv
UNION ALL SELECT 'col', NULL, cv, count(DISTINCT research_id) FROM pv GROUP BY cv
UNION ALL SELECT 'funnel', '<k>', NULL, <same funnel subqueries as above>      -- one row per step
```

Margins are counted over `pv`, the same set the cells come from, so every patient in a margin
is in a cell of that line. (Margins over the axis scans would include a patient who matched a
row on one report and the cell's fact on another, and the row total minus its cells would
recover that patient.)

The pivot computes the funnel too, so its total has the same delta rule as `count`.

### `suppress.py`

```python
import uccc_genomics.config  # noqa: F401  loads the repo .env (COHORT_ROUND)
MIN_CELL = 5
ROUND = int(os.environ.get("COHORT_ROUND", "1"))

def floor(n: int | None) -> int | None      # moved verbatim from cohort_api.floor: 0 stays 0, 1..4 -> None, else rounded to ROUND, at least MIN_CELL
```

Raw inputs (dataclasses, never returned by any public function):

```python
@dataclass
class RawCount:
    funnel: list[int]                       # step 0 = population, step k = after criterion k
    reports: int
    by_year: dict[int, int]                 # first-qualifying year -> patients
    year_complete: dict[int, bool]
    breakdowns: dict[str, dict[str, int]]   # dim -> value -> patients (hit)
    denominators: dict[str, dict[str, int]] # dim -> value -> patients (pop)
    loosen: dict[str, int]                  # criterion id -> raw count without it (only when computed)

@dataclass
class RawPivot:
    funnel: list[int]
    cells: dict[tuple[str, str], int]
    rows: dict[str, int]
    cols: dict[str, int]
```

Result models (Pydantic, the only shapes that leave the module):

```python
class FunnelStep(BaseModel):    criterion: str | None; patients: int | None   # None criterion = the population
class YearCount(BaseModel):     year: int; patients: int | None; complete: bool
class BreakdownCell(BaseModel): value: str; patients: int | None; denominator: int | None
class Loosen(BaseModel):        drop: str; patients: int
class CountResult(BaseModel):
    cohort_id: str; patients: int | None; reports: int | None; denominator: int | None
    funnel: list[FunnelStep]; by_year: list[YearCount]; breakdowns: dict[str, list[BreakdownCell]]
    notes: list[str]; loosen: list[Loosen]; min_cell: int = MIN_CELL
class PivotCell(BaseModel):     row: str; col: str; patients: int | None
class Margin(BaseModel):        value: str; patients: int | None
class PivotResult(BaseModel):
    cohort_id: str; rows: str; cols: str; patients: int | None
    cells: list[PivotCell]; row_totals: list[Margin]; col_totals: list[Margin]
    notes: list[str]; min_cell: int = MIN_CELL

def suppress_count(d: Definition, raw: RawCount) -> CountResult
def suppress_pivot(d: Definition, raw: RawPivot) -> PivotResult
```

No result field is a small structural integer (no step index), so the "no 1–4 anywhere" walk
stays meaningful.

#### Rules (all on raw values; every number in a result is `floor()`ed)

1. **Funnel** (`_funnel(raw: list[int]) -> list[int | None]`): walk the steps keeping `last`,
   the raw value of the last shown step. Step `n` is `floor(n)`, but it is hidden (`None`) if
   `last is not None and 0 < last - n < MIN_CELL`. If shown, `last = n`. Example:
   `[20, 18, 10, 9, 3] -> [20, None, 10, None, None]`. `denominator` = step 0 and
   `patients` = the last step, **after** this rule, so `patients` can never contradict the
   funnel.
2. **Line rule** (secondary suppression, `_line(values, total)`): a line is the ordered list of
   shown/hidden values plus its total, and the total is never a candidate. If exactly one value
   in the line (total included) is `None`, the smallest shown positive non-total value is hidden
   (ties go to the first in line order). Zeros are known and never candidates. This is
   `cohort_api.suppress`'s rule, generalised.
3. **One-dimensional lists**: `by_year` (line order ascending year, total `patients`), each
   breakdown's `patients` (line order ascending value, total `patients`) and each breakdown's
   `denominator` (same order, total `denominator`). One rule pass each. Denominators are output
   **only for values present in that breakdown's cells**, so a small population value with no
   cohort patients is never listed. Those unlisted values are a hidden value of the denominator
   line when each of them is under 5 (their patients are then 1..4 in all and `denominator`
   minus the listed ones would give them): that line is passed to `_line` with one extra `None`.
   The same applies to `by_year` when `0 < patients - sum(by_year) < 5` (patients with no dated
   report). Output order: `by_year` ascending. Breakdown cells: shown
   cells by `patients` descending, then hidden, ties by `value`. Sorting happens after
   suppression, so the order says nothing about hidden values.
4. **Pivot (two-way)**: rows `R` and cols `C` sorted ascending. Absent cells are 0. Lines, in
   this order: each row `[cells r×C…, row_total r]`, each col `[cells R×c…, col_total c]`, the
   margin column `[row_totals…, total]` and the margin row `[col_totals…, total]`. Apply the line
   rule to every line, and repeat full passes until one changes nothing. Output: cells present in
   `raw.cells` sorted by `(row, col)`; margins sorted by value.
5. **Whole-cohort rule**: if `patients` is `None`, `reports` is `None`, `by_year` is `[]`,
   every breakdown is `[]` (keys kept), and pivot `cells`/`row_totals`/`col_totals` are `[]`.
   The funnel stays: each step is an ordinary floored count of a prefix cohort, with the delta
   rule applied.
6. **Loosen** (count only): computed when `patients` (after rule 1) is `None` or raw `patients`
   is under `MIN_CELL`. For each criterion `cj`, the raw count `L` of the definition without it
   (`apply(d, remove_criterion cj)`, compiled and run on the same connection). A suggestion
   `{drop: cj, patients: floor(L)}` is kept only if `floor(L)` is not `None`,
   `L - raw_patients >= MIN_CELL`, **and** for every raw funnel step `s`: if `s` is shown, `L == s`
   or `|L - s| >= MIN_CELL`; if `s` was hidden by rule 1, `L != s`. `L` is a set nested in every
   earlier step, so a suggestion 1..4 from a shown step, or equal to a hidden one, would reveal
   the delta rule 1 hid. Sorted by `patients` descending, then `drop`. Worked examples: steps
   `[15, 7, 7, 6]` hide the last step (delta 1), and dropping a redundant criterion would return
   6. Steps `[20, 17, 3]` show `[20, None, None]`; dropping c2 gives 17, and a shown 17 beside
   20 would reveal the 3 patients missing from the second step, so it is not offered.

### `queries.py`

```python
from uccc_genomics_mcp.server import DEID_DB, get_db     # the hardened read-only connection

_vocab = {"mtime": None, "v": None}

def vocabulary() -> Vocabulary        # cached on os.path.getmtime(DEID_DB), as cohort_api.vocab()
def count(d: Definition) -> CountResult
def pivot(d: Definition) -> PivotResult
```

`count` calls `vocabulary().check(d)`, then `compile(d)`, and opens **one** `get_db()`
connection (closed in `finally`). It runs the statement, builds `RawCount`, runs the loosen
statements on the same connection when rule 6 applies, and returns
`suppress_count(d, raw)` with `cohort_id(d)` and `data_notes(d)`. `pivot` does the same with
`compile_pivot`/`suppress_pivot`, and raises `DefinitionError` when `d.pivot is None`. Nothing
else in the package touches DuckDB. No result type carries `research_id`, `report_id`, dates or
row-level values.

### What leaves the host, and the small-cell rule

This package is a new output path, though it has no transport yet. The REST/MCP issues expose
it. Everything it returns is one of `CountResult`, `PivotResult`, `Vocabulary`/`VocabEntry`
(floored, ≥ 5) or a `Definition` (caller input, normalised). Every count passes `floor()`, the
line rule, the funnel delta rule and the whole-cohort rule. Loosen counts also pass the delta
rule against the cohort and every funnel step. The §3.6 multi-select (union) differencing stays as it is in phase 1:
accepted under the audit log that the REST layer writes, as is a breakdown cell against its
denominator (deviation 13). Pivot labels from `sub`/`val` axes are folded to `other` below 5
patients (deviation 7), and the vocabulary offers counts only for parentless entries (deviation 14). Tests pin all of this (below).

`research_id`/`report_id`: unaffected. The package reads them inside SQL only. It adds no hash,
key or hash input, and returns no ids.

## Acceptance criteria

- [ ] `uccc_genomics_mcp.cohort` exists with the files, public surface and signatures above.
      `pydantic>=2.11` is declared in `mcp/pyproject.toml`, and `uv.lock` is updated, so
      `uv sync --locked` passes.
- [ ] `json_schema()` exposes every criterion kind (`alteration`, `biomarker`, `ihc`,
      `expression`, `specimen`, `actionability`, `any_of`) and the alias `class` (not `class_`).
      `operation_json_schema()` exposes all seven ops.
- [ ] Normalisation: gene case, list order and duplicates, an explicit default `tier`, `mode`
      and the order of `any_of` members all give an equal `Definition` and the same `cohort_id`.
      So do a different `name`, `breakdown`, `pivot`, criterion ids and criterion order. A
      different value gives a different id. One fixed definition's id is pinned as a literal.
- [ ] Deferred features fail with `DefinitionError` and the messages above: kinds `sequence`,
      `data`, `tested_negative` and `exclude` (top level and inside `any_of`), modes `exclude`
      and `tested_negative`, scope `report`, and version 2.
- [ ] Static validation rejects: `aa` with two genes; `aa` with class `fusion`; `at_least` off
      the cut points (TMB 11, CPS 5); `at_least` on MSI; `call` together with `at_least`; IHC
      `at_least` without `measure`; an empty `specimen`; duplicate ids; a pivot with
      `rows == cols`, an unknown criterion or a specimen criterion axis.
- [ ] Every operation works through `apply` with a dict op and leaves the input unchanged.
      `add_criterion` assigns `c{max+1}`. `remove_criterion` clears a pivot that references
      it. Unknown ids and duplicate ids raise `DefinitionError`.
- [ ] `Vocabulary` on the synthetic mart: every parentless entry has `patients >= 5` and every
      entry with a parent has `patients = None`; `THYM`, `positive`
      under `ERBB2 (Her2/Neu)` and `G13D` are absent; `check` rejects them, naming the field.
      `search("erbb2")` returns `alteration.gene ERBB2` and `ihc.marker ERBB2 (Her2/Neu)`.
- [ ] `compile`/`compile_pivot` raise `DefinitionError` for a pivot axis, criterion axis or
      breakdown dimension that is not in the allow-lists, even on a `Definition` built with
      `model_construct`/`model_copy(update=...)`.
- [ ] `compile` for each kind contains that kind's `fact_cond` and binds the values as
      parameters. No caller value appears in the SQL text. Only `mart.report`/`mart.fact` are
      referenced. The same definition compiles to identical output.
- [ ] Questions 1–9, 12, 13, 15, 16 and 20 give the expected results in the test plan.
- [ ] Suppression: the funnel delta rule, line rule, two-way pivot rule, whole-cohort rule and
      loosen rule each give the expected results in the test plan.
- [ ] For every count and pivot result in the test module, walking it finds no key named
      `research_id` or `report_id`, no `int` (not `bool`) from 1 to 4, and no string equal to a
      fixture `research_id` or `report_id`.
- [ ] `tests/test_cohort_api.py` passes unchanged after `cohort_api` imports `floor`/`MIN_CELL`.
- [ ] `uv run pytest -q` passes. The dashboard check is n/a (no `dashboard/` code changes).
- [ ] Docs updated per Deviations.

## Test plan

New `tests/test_cohort.py`. It never reads `$DATA/raw`, the PHI file or the real de-id file,
except for the one skip-guarded real-DB test.

### Fixture

A `cohort_db` fixture (function scope is fine; the DB is small) creates `tmp_path/"mart.duckdb"`
with `CREATE SCHEMA mart` and the two tables, with exactly #33's columns and types:

```sql
CREATE TABLE mart.report (research_id VARCHAR, vendor VARCHAR, report_id VARCHAR, year INTEGER,
  year_complete BOOLEAN, sex VARCHAR, age INTEGER, age_band VARCHAR, oncotree VARCHAR, organ VARCHAR,
  disease VARCHAR, assay_class VARCHAR, assay_name VARCHAR, purity DOUBLE, site_type VARCHAR, site VARCHAR,
  has_wts BOOLEAN);
CREATE TABLE mart.fact (research_id VARCHAR, vendor VARCHAR, report_id VARCHAR, kind VARCHAR, key VARCHAR,
  sub VARCHAR, val VARCHAR, num DOUBLE, unit VARCHAR, tier VARCHAR);
```

It then monkeypatches `queries.get_db` to
`lambda: server.harden(duckdb.connect(path, read_only=True))`, `queries.DEID_DB` to `path`,
`queries._vocab` to `{"mtime": None, "v": None}`, and `suppress.ROUND` to `1`.

Small helpers write the rows. Each patient `<pid>` has one report `<pid>r` unless noted.
`research_id = pid`. `age_band` is derived as in `mart.sql`. `year_complete = true` unless noted.
`disease = oncotree`, `assay_name = 'synthetic'`, and mutation facts have
`sub = 'mutation'` with the given `tier`. A specimen site or type sets both the report column and
a `specimen` fact. Purity sets `mart.report.purity` and a `specimen`/`purity`/`%` fact.

| group | patients | report attributes | facts |
|---|---|---|---|
| NSCLC (`Lung`) | `n0`–`n24` | caris tissue, age 60; `n0`–`n9` 2022, `n10`–`n24` 2024; **`n10` also has report `n10b`**: caris **liquid** 2023, age NULL | KRAS mutation `G12C` pathogenic on `n0`,`n1`,`n2`, `n10r`, `n10b`, `n11`–`n15`; KRAS `G12C` **vus** on `n16`; ALK fusion `EML4` plus EML4 fusion `ALK` on `n3`–`n8`; RET fusion `KIF5B` plus KIF5B fusion `RET` on `n17`,`n18` |
| COADREAD (`Bowel`) | `b0`–`b19`, 2023 | `b0`–`b11` caris tissue (`b0`–`b5` age 40, `b6`–`b11` age 70); `b12`–`b19` fmi tissue, age NULL; `b0`–`b5` site_type `metastatic`, site `liver` | MSI `high` on `b0`–`b4`, `stable` on the rest; TMB 12.0 `mut/Mb` `high` on `b0`,`b1`,`b2`,`b5`,`b6`, TMB 3.0 `low` on the rest; PIK3CA `E545K` pathogenic on `b7`–`b9`; RET `M918T` pathogenic on `b10`–`b12`; IDH1 `R132C` pathogenic on `b13`–`b15` |
| MEL (`Skin`) | `m0`–`m9`, 2022 | fmi tissue, male | TMB 20.0 `high` on `m0`–`m7`, 4.0 `low` on `m8`,`m9`; MSI `stable` on all; actionability `fmi_fda_any_indication` (sub `BRAF`, val `dabrafenib`) on `m0`–`m5` |
| BRCA (`Breast`) | `br0`–`br14`, 2024 | caris tissue, age 55; `br0`,`br1` site_type `metastatic`, site `liver` | ihc `ERBB2 (Her2/Neu)`: `her2-low` (15.0 `% stained`) on `br0`–`br4`, `her2-ultralow` on `br5`–`br9`, `positive` on `br10`,`br11`; ERBB2 `amplification` on `br10`,`br11`; ihc `ER` `positive` on `br0`–`br9`, `negative` on `br10`–`br14`; PIK3CA `H1047R` pathogenic on `br0`–`br4`; PIK3CA `E545K` pathogenic on `br10`,`br11`; actionability `caris_level1` (sub `ERBB2`, val `trastuzumab`) on `br0`, `br8`–`br11` |
| OV (`Ovary`) | `ov0`–`ov9`, 2023 | caris tissue, `has_wts` true | BRCA1 `E1836K` pathogenic on `ov0`–`ov4`; LOH 20.0 `%` `high` on `ov2`–`ov7`, 5.0 `low` on `ov0`,`ov1`,`ov8`,`ov9`; expression TACSTD2 80.0 `percentile` on `ov0`–`ov4`, 40.0 on `ov5`–`ov9` |
| STAD (`Esophagus/Stomach`) | `st0`–`st19`, 2024 | caris tissue | ihc `CLDN18` `positive` on `st0`–`st9`, `negative` on `st10`–`st19`; ihc `PD-L1` sub `22c3` unit `CPS`: 15.0 `positive` on `st0`–`st4` and `st10`–`st14`, 0.0 `negative` on the rest; ERBB2 `amplification` on `st0`–`st4` |
| PAAD (`Pancreas`) | `pa0`–`pa14`, 2023 | caris tissue; `has_wts` true on `pa0`–`pa4`; purity 40 on `pa0`–`pa4`, 20 on the rest; `pa0`–`pa4` site_type `metastatic`, site `liver` | KRAS `G12D` pathogenic on `pa0`–`pa9` |
| CHOL (`Biliary Tract`) | `ch0`–`ch14`, 2025, **`year_complete` false** | fmi tissue | TP53 `R273H` pathogenic on `ch0`–`ch5`; CDKN2A `loss` on `ch0`–`ch6`; IDH1 `R132C` pathogenic on `ch7`,`ch8` |
| THYM (`Thymus`) | `t0`,`t1`, 2022 | fmi tissue | none |

Totals: 132 patients and 133 reports. Population sizes: NSCLC 25, COADREAD 20, STAD 20,
BRCA 15, CHOL 15, PAAD 15, MEL 10, OV 10, THYM 2.

### Question tests (`test_question_<n>`; definitions are built with `parse` and compared on `CountResult`/`PivotResult` fields)

| # | definition | expected |
|---|---|---|
| 1a | population `oncotree [NSCLC]`, `years [2023, 2025]`; c1 alteration `gene [KRAS] aa [G12C]` | funnel `[15, 6]`; patients 6; denominator 15; reports 7 (`n10` has 2); by_year `[{2023, None, true}, {2024, None, true}]` (2023 is 1, so the line rule hides 2024's 5) |
| 1b | same without `years` | funnel `[25, 9]`; by_year `[{2022, None}, {2023, None}, {2024, 5}]` (two hidden cells, so no extra hiding); the `n16` VUS is not counted |
| 2 | no criteria; pivot `rows oncotree`, `cols year` | patients 132. Shown cells: BRCA×2024 15, CHOL×2025 15, COADREAD×2023 20, NSCLC×2024 15, PAAD×2023 15, STAD×2024 20. Hidden: MEL×2022, NSCLC×2022, NSCLC×2023, OV×2023, THYM×2022. row_totals hidden: MEL, OV, THYM, the rest shown (NSCLC 25). col_totals 2022 22, 2023 46, 2024 50, 2025 15 |
| 3 | population `oncotree [COADREAD]`, `age_band ["<50"]` | patients 6; notes contain the `age` note. Also population `[COADREAD]`, breakdown `[age_band]`: cells `{"unknown": 8, "65-74": 6, "<50": 6}`, each denominator equal to its patients |
| 4 | c1 `any_of [biomarker MSI call [high], biomarker TMB at_least 10]`; breakdown `[oncotree]` | patients 15; oncotree cells `MEL 8 (denominator 10)`, `COADREAD 7 (denominator 20)`, and no other values |
| 5 | c1 alteration `gene [ALK, RET] class [fusion]`; pivot `rows c1.key`, `cols oncotree` | patients 8; cells ALK×NSCLC and RET×NSCLC both `None`; row_totals ALK and RET `None`; col_totals NSCLC 8 |
| 6 | c1 `any_of [ihc marker "ERBB2 (Her2/Neu)" call [her2-low, her2-ultralow], alteration gene [ERBB2] class [amplification, mutation]]`; breakdown `[oncotree]` | patients 17; cells `BRCA 12 (15)`, `STAD 5 (20)`; notes contain `ihc` |
| 7 | population `[OV, PAAD]`; c1 `any_of [alteration gene [BRCA1], biomarker LOH call [high]]`; breakdown `[oncotree]`; pivot `rows c1.key`, `cols oncotree` | count: funnel `[25, 8]`, cells `OV 8 (10)` only. Pivot: BRCA1×OV 5, LOH×OV 6, row_totals BRCA1 5 and LOH 6, col_totals OV 8 |
| 8 | population `[OV]`; c1 expression `[TACSTD2]` (no threshold); c2 expression `[TACSTD2] percentile_at_least 75` | funnel `[10, 10, 5]`; notes contain `expression` |
| 9 | population `[STAD]`; c1 ihc `CLDN18`; c2 ihc `PD-L1 measure CPS`; c3 ihc `CLDN18 call [positive]`; c4 ihc `PD-L1 measure CPS at_least 10` | funnel `[20, 20, 20, 10, 5]` |
| 12 | population `[CHOL]`; c1 alteration `gene [TP53, CDKN2A, IDH1]`; pivot `rows c1.key`, `cols c1.sub` | patients 9; by_year `[{2025, 9, false}]`. Pivot: CDKN2A×loss 7, TP53×mutation `None`, IDH1×mutation `None`; row_totals CDKN2A 7, IDH1 `None`, TP53 `None`; col_totals loss 7, mutation 8 |
| 13 | population `[BRCA]`; c1 ihc `ER call [positive]`; c2 alteration `gene [PIK3CA] aa [H1047R, E545K]` | funnel `[15, 10, 5]` |
| 15 | c1 specimen `site_type [metastatic] site [liver]`; breakdown `[oncotree]` | patients 13; cells `COADREAD 6 (20)`, `PAAD None (15)`, `BRCA None (15)` (BRCA's 2 hidden, then PAAD's 5 by the line rule); notes contain `specimen` |
| 16 | population `[PAAD]`; c1 alteration `gene [KRAS] aa [G12D]`; breakdown `[has_wts]` | funnel `[15, 10]`; cells `false 5 (10)`, `true 5 (5)`; notes contain `has_wts`. Adding c2 specimen `purity_at_least 30` gives funnel `[15, 10, 5]` |
| 20 | c1 actionability `evidence [caris_level1, fmi_fda_any_indication]`; breakdown `[oncotree]` | patients 11; cells `MEL 6 (10)`, `BRCA 5 (15)`; notes contain `fda` |

### Suppression tests

- `test_funnel_delta_rule`: `suppress._funnel([20, 18, 10, 9, 3]) == [20, None, 10, None, None]`.
  End to end: population `[CHOL]`; c1 alteration `[TP53, CDKN2A]`, c2 `[CDKN2A]`, c3 `[TP53]`
  give funnel `[15, 7, 7, None]`. Patients `None` (raw 6), so the whole-cohort rule applies:
  reports `None`, by_year `[]`, breakdown `{"oncotree": []}` with breakdown `[oncotree]`, and
  loosen `[]` (every drop is within 4 of 6).
- `test_loosen`: population `[CHOL]`; c1 alteration `[IDH1]` gives funnel `[15, None]` and
  loosen `[{drop: "c1", patients: 15}]`. Population `[STAD]`; c1 ihc `CLDN18 call [positive]`,
  c2 ihc `PD-L1 measure CPS at_least 10`, c3 ihc `ER call [positive]` gives funnel
  `[20, 10, 5, 0]`, patients 0 and loosen `[{drop: "c3", patients: 5}]`.
- `test_loosen_does_not_repeat_hidden_funnel_steps`: `suppress_count` on a `RawCount` with funnel
  `[20, 17, 3]` (and `[20, 18, 3]`) and loosen `{c1: 20, c2: <step 1>, c3: 9}` offers c1 and c3
  but not c2; with c3 = 16 (4 from the shown 20) only c1 is offered.
- `test_unlisted_small_remainder_is_a_hidden_value`: a synthetic mart with 18 female and 3 male
  patients in the population, 12 female patients in the cohort (2 with no dated report): the
  female denominator and the 2022 count are `None`.
- `test_line_rule`: `_line([12, None], total)` hides 12. `[None, None, 5]` stays as it is. A
  zero is never chosen. Ties go to the first in line order.
- `test_pivot_two_way`: questions 2, 5 and 12 above, plus the invariant that in every returned
  pivot, no line (each row with its total, each column with its total, both margin lines with
  the grand total, absent cells as 0) has exactly one `None`.
- `test_pivot_rare_fact_values_become_other`: a `c1.val` axis on the HER2 IHC criterion folds
  `positive` (2 patients) into `other`; a `c1.val` axis on `RET` leaves neither the fusion
  partner nor the protein change in `model_dump()`; a `c1.key` axis keeps its gene names.
- `test_pivot_margins_count_only_patients_in_a_cell`: six patients with two reports in
  different years, c1 on the first and c2 on the second: a `year` × `c1.key` pivot has no 2024
  row, and every line has other than one `None`.
- `test_no_small_numbers_and_no_ids`: parametrised over every question definition (count, and
  pivot where set) plus the suppression definitions. Walk each `result.model_dump()` as
  `tests/test_cohort_api.py::walk` does: no key `research_id`/`report_id`, no non-bool `int`
  from 1 to 4, and no string in the set of fixture research_ids and report_ids. Also walk
  `vocabulary().model_dump()`: every parentless entry `patients >= 5`, children `None`, no fixture id.

### Definition, operation, vocabulary and compile tests

- `test_cohort_id_stable`: the equivalences and differences in the acceptance criteria, plus
  `cohort_id(parse({"criteria": [{"id": "c1", "kind": "alteration", "gene": ["KRAS"], "aa": ["G12C"]}]}))`
  pinned as a literal (computed once at implementation time). Pinning catches any later change to
  normalisation or canonical JSON that would orphan saved cohorts.
- `test_deferred_features_rejected`, `test_static_validation`: the lists in the acceptance
  criteria. Assert `DefinitionError` and a message fragment.
- `test_operations`: each op, including the failure cases, and that the input definition is
  unchanged (`==` to a copy taken before).
- `test_vocabulary_floor_and_check`, `test_search`: per the acceptance criteria. Also that
  `check` accepts every fixture value the question definitions use.
- `test_compile_validates_names_it_puts_in_the_sql`: `compile_pivot` of a definition copied with
  `Pivot.model_construct(rows="(SELECT 1); --", ...)`, an axis naming no criterion, and
  `compile` with a breakdown `"sex; DROP TABLE x"` raise `DefinitionError`.
- `test_compile_each_kind`: for one definition per kind (and an `any_of`), assert the `fact_cond`
  fragment is in the SQL, the values are in `params`, the value strings (`"KRAS"`, `"G12C"`,
  `"CLDN18"`, …) are not in the SQL text, `"unified."`/`"caris."`/`"fmi."` do not appear, and
  `compile(d) == compile(d)`.
- `test_json_schema`: the kinds, the `class` alias and the ops are present. A §3.1-style example
  without the phase 2 `exclude` criterion parses.
- `test_real_db_matches_hand_written_sql`: skipped when `DEID_DB` is absent or
  `deid_lacks_mart()` (new conftest helper: true when `mart.fact` is missing from the real de-id
  file). On the host it monkeypatches nothing and runs `count(parse({"criteria": [{"id": "c1",
  "kind": "alteration", "gene": ["TP53"], "aa": ["R175H"]}]}))`. It asserts `patients` equals
  `floor()` of a hand-written count over `unified.variant` (`gene = 'TP53'`,
  `regexp_replace(hgvs_p, '^p\.', '') = 'R175H'`, `tier IN ('pathogenic', 'likely_pathogenic')`,
  distinct `research_id`). This checks compiler, mart and unified views against each other. It
  prints nothing.

Commands: `uv lock`, `uv sync --locked`, `uv run pytest -q`. The dashboard `npm test` is n/a.
`uvx ruff check src mcp tests` is advisory.

## Risks

- **Seam blast radius.** Every future count (REST, MCP, chat) goes through `compile` and
  `suppress`. A wrong `fact_cond` skews a whole criterion kind. A weak suppression rule leaks on
  every surface. Mitigations: per-kind compile tests, the per-question known-answer tests, the
  walk test and one real-DB cross-check against `unified.*`.
- **Secondary suppression is heuristic.** "No line with exactly one hidden value" does not stop
  every linear-algebra recovery. A patient can sit in several cells (several reports or
  several genes), so lines do not sum exactly. This is the phase 1 rule
  (`COHORT_TOOL.md`), extended to two axes as §3.6 asks. The residual risk is the one already
  documented, with the audit log and campus-only access as the backstop.
- **Union differencing stays open** (§3.6 multi-select row): OR-ing a value into a population
  list can expose that value's small in-cohort count by subtraction. That is unchanged from
  phase 1 and still for Sean to decide. It is not made worse here, because the vocabulary floor
  still applies per value.
- **Real DB lags the code.** Until the daily rebuild after #33 lands on the host, the real file
  may have no `mart.*`. The real-DB test skips (`deid_lacks_mart()`) rather than failing.
- **Query cost.** Each criterion adds one `EXISTS` scan of `mart.fact`, filtered by `kind`.
  Loosen re-runs the statement up to 10 times, only when the cohort is under the floor. That is
  fine at this data size. If it is not, all loosen counts can come from one statement.
- **Fixture drift from `mart.sql`.** The test builds the mart tables by hand. If #33's columns
  change, `test_pipeline.py`'s pinned column lists fail first, and this fixture must follow.
- **`cohort_id` is a contract.** Saved cohorts key on it. Changing normalisation or the canonical
  JSON changes ids, which the pinned literal catches. A deliberate change bumps
  `SCHEMA_VERSION`.
