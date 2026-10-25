"""Cohort definition (COHORT_DISCOVERY.md §3.1): models, normalisation, cohort_id and operations.

Every constructed `Definition` is already normalised (validators sort, dedupe and fold case), so
equal cohorts compare equal and hash to the same `cohort_id`. A definition changes only through
`apply(definition, op)`. Spec: docs/specs/34-cohort-module-definition-operations.md.
"""
import hashlib
import json
import re
from typing import Annotated, Literal, get_args

from pydantic import (AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError,
                      field_validator, model_validator)

SCHEMA_VERSION = 1
AltClass = Literal["mutation", "amplification", "loss", "fusion"]
Tier = Literal["pathogenic", "likely_pathogenic", "vus", "unclassified"]   # benign is never an alteration (#32)
Evidence = Literal["caris_level1", "fmi_fda_any_indication", "fmi_trial"]
BreakdownDim = Literal["oncotree", "organ", "sex", "age_band", "vendor", "assay_class", "site_type", "has_wts"]
POP_DIMS = ("oncotree", "organ", "sex", "age_band", "vendor", "assay_class")   # = mart.report columns
BREAKDOWN_DIMS = get_args(BreakdownDim)
PIVOT_DIMS = BREAKDOWN_DIMS + ("year",)
ALT_CLASSES = get_args(AltClass)
TIERS = get_args(Tier)
EVIDENCE = get_args(Evidence)
DEFAULT_TIERS = ["likely_pathogenic", "pathogenic"]
# COHORT_DISCOVERY.md §3.1 fixed cut points (open question 4); no free numbers.
CUT_POINTS = {"biomarker.TMB": [10.0, 16.0, 20.0], "ihc.TPS": [1.0, 50.0], "ihc.CPS": [1.0, 10.0, 20.0],
              "expression.percentile": [50.0, 75.0, 90.0], "specimen.purity": [20.0, 30.0, 50.0]}
DEFERRED_KINDS = ("sequence", "data", "tested_negative", "exclude")
ID_RE = re.compile(r"^c[1-9][0-9]{0,2}\Z")
AXIS_RE = re.compile(r"^(c[1-9][0-9]{0,2})\.(key|sub|val)\Z")

_CONFIG = ConfigDict(extra="forbid", frozen=True, validate_by_name=True, validate_by_alias=True,
                     serialize_by_alias=True)


class DefinitionError(ValueError):
    """The one error type for callers (the REST layer maps it to 400)."""


def _error(e: ValidationError) -> DefinitionError:
    first = e.errors()[0]
    loc = ".".join(map(str, first["loc"]))
    msg = first["msg"].removeprefix("Value error, ")
    return DefinitionError(f"{loc}: {msg}" if loc else msg)


# --- normalisers ---------------------------------------------------------------------------------

def _strs(case: str | None = None):
    """Strip, reject empty, fold case (`upper`/`lower`), dedupe, sort."""
    def norm(values: list[str]) -> list[str]:
        out = set()
        for v in values:
            v = v.strip()
            if not v:
                raise ValueError("empty string in list")
            out.add(v.upper() if case == "upper" else v.lower() if case == "lower" else v)
        return sorted(out)
    return AfterValidator(norm)


def _sorted_unique(values: list) -> list:
    return sorted(set(values))


Strs = Annotated[list[str], _strs()]
Genes = Annotated[list[str], _strs("upper")]
Lowers = Annotated[list[str], _strs("lower")]
Sorted = AfterValidator(_sorted_unique)


def _check_cut_point(name: str, value: float | None, key: str) -> None:
    if value is not None and value not in CUT_POINTS[key]:
        raise ValueError(f"{name} must be one of {CUT_POINTS[key]}, not {value}")


def _reject_deferred(item):
    """Deferred features get a clear message instead of Pydantic's generic discriminator error."""
    if isinstance(item, dict):
        if item.get("kind") in DEFERRED_KINDS:
            raise ValueError(f"criterion kind '{item['kind']}' is not supported yet")
        if item.get("mode") not in (None, "include"):
            raise ValueError(f"criterion mode '{item['mode']}' is not supported yet; criteria are include-only")
    return item


def _reject_deferred_all(items):
    if isinstance(items, list):
        for item in items:
            _reject_deferred(item)
    return items


# --- criteria ------------------------------------------------------------------------------------

class Population(BaseModel):
    model_config = _CONFIG
    oncotree: Annotated[list[str], Field(max_length=100), _strs()] = []
    organ: Annotated[list[str], Field(max_length=100), _strs()] = []
    sex: Annotated[list[str], Field(max_length=10), _strs()] = []
    age_band: Annotated[list[str], Field(max_length=10), _strs()] = []
    vendor: Annotated[list[str], Field(max_length=10), _strs()] = []
    assay_class: Annotated[list[str], Field(max_length=10), _strs()] = []
    years: tuple[int, int] | None = None            # inclusive [from, to]; from <= to

    @field_validator("years")
    @classmethod
    def _years_ordered(cls, v):
        if v is not None and v[0] > v[1]:
            raise ValueError(f"years must be [from, to] with from <= to, not {list(v)}")
        return v


class _Criterion(BaseModel):
    model_config = _CONFIG
    id: str | None = None                           # required at the top level, absent in any_of members
    mode: Literal["include"] = "include"            # exclude / tested_negative: phase 2


class Alteration(_Criterion):
    kind: Literal["alteration"]
    gene: Annotated[list[str], Field(min_length=1, max_length=100), _strs("upper")]
    aa: Annotated[list[str], Field(max_length=50), _strs()] = []             # needs exactly one gene
    class_: Annotated[list[AltClass], Sorted] = Field(default=[], alias="class", validate_default=True)   # [] = any class
    tier: Annotated[list[Tier], Sorted] = DEFAULT_TIERS                      # [] -> DEFAULT_TIERS

    @field_validator("aa")
    @classmethod
    def _aa_needs_one_gene(cls, v, info):
        if v and len(info.data.get("gene", [])) != 1:
            raise ValueError("aa needs exactly one gene")
        return v

    @field_validator("class_")
    @classmethod
    def _class_all_is_any(cls, v, info):
        if info.data.get("aa"):
            if v not in ([], ["mutation"]):
                raise ValueError("aa applies to class mutation only")
            return ["mutation"]
        return [] if v == sorted(ALT_CLASSES) else v

    @field_validator("tier")
    @classmethod
    def _tier_default(cls, v):
        return v or list(DEFAULT_TIERS)


class Biomarker(_Criterion):
    kind: Literal["biomarker"]
    name: Literal["TMB", "MSI", "LOH"]
    call: Annotated[list[str], Field(max_length=10), _strs("lower")] = []
    at_least: float | None = None                   # TMB only, from CUT_POINTS["biomarker.TMB"]

    @model_validator(mode="after")
    def _check(self):
        if self.call and self.at_least is not None:
            raise ValueError("call and at_least are mutually exclusive")
        if self.at_least is not None:
            if self.name != "TMB":
                raise ValueError("at_least is allowed for TMB only")
            _check_cut_point("at_least", self.at_least, "biomarker.TMB")
        return self


class Ihc(_Criterion):
    kind: Literal["ihc"]
    marker: str = Field(min_length=1)
    clone: str | None = None
    call: Annotated[list[str], Field(max_length=20), _strs("lower")] = []
    measure: Literal["TPS", "CPS"] | None = None
    at_least: float | None = None                   # needs measure; from CUT_POINTS[f"ihc.{measure}"]

    @field_validator("marker")
    @classmethod
    def _marker_strip(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("marker must not be empty")
        return v

    @field_validator("clone")
    @classmethod
    def _clone_lower(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        if not v:
            raise ValueError("clone must not be empty")
        return v

    @model_validator(mode="after")
    def _check(self):
        if self.call and (self.measure or self.at_least is not None):
            raise ValueError("call excludes measure and at_least")
        if self.at_least is not None:
            if self.measure is None:
                raise ValueError("at_least needs measure")
            _check_cut_point("at_least", self.at_least, f"ihc.{self.measure}")
        return self


class Expression(_Criterion):
    kind: Literal["expression"]
    gene: Annotated[list[str], Field(min_length=1, max_length=20), _strs("upper")]
    percentile_at_least: float | None = None        # CUT_POINTS["expression.percentile"]

    @field_validator("percentile_at_least")
    @classmethod
    def _cut(cls, v):
        _check_cut_point("percentile_at_least", v, "expression.percentile")
        return v


class Specimen(_Criterion):
    kind: Literal["specimen"]
    site_type: Annotated[list[str], Field(max_length=20), _strs("lower")] = []
    site: Annotated[list[str], Field(max_length=50), _strs("lower")] = []
    purity_at_least: float | None = None            # CUT_POINTS["specimen.purity"]

    @model_validator(mode="after")
    def _check(self):
        if not (self.site_type or self.site or self.purity_at_least is not None):
            raise ValueError("specimen needs site_type, site or purity_at_least")
        _check_cut_point("purity_at_least", self.purity_at_least, "specimen.purity")
        return self


class Actionability(_Criterion):
    kind: Literal["actionability"]
    evidence: Annotated[list[Evidence], Field(min_length=1), Sorted]


Leaf = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability,
                 Field(discriminator="kind")]


def _canon(c: BaseModel) -> dict:
    return c.model_dump(mode="json", by_alias=True, exclude_defaults=True, exclude={"id"})


class AnyOf(_Criterion):
    kind: Literal["any_of"]
    of: Annotated[list[Leaf], Field(min_length=2, max_length=8)]

    reject_deferred = field_validator("of", mode="before")(_reject_deferred_all)

    @field_validator("of")
    @classmethod
    def _order_independent(cls, v):
        return sorted(v, key=lambda m: json.dumps(_canon(m), sort_keys=True))


Criterion = Annotated[Alteration | Biomarker | Ihc | Expression | Specimen | Actionability | AnyOf,
                      Field(discriminator="kind")]


class Pivot(BaseModel):
    model_config = _CONFIG
    rows: str
    cols: str


def _has_specimen(c) -> bool:
    return c.kind == "specimen" or (c.kind == "any_of" and any(m.kind == "specimen" for m in c.of))


class Definition(BaseModel):
    model_config = _CONFIG
    version: Literal[1] = 1
    name: str = Field(default="", max_length=200)
    population: Population = Population()
    criteria: list[Criterion] = Field(default=[], max_length=10)
    scope: Literal["patient"] = "patient"
    breakdown: list[BreakdownDim] = Field(default=[], max_length=4)
    pivot: Pivot | None = None

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, v):
        if v != 1:
            raise ValueError(f"unsupported definition version {v}")
        return v

    @field_validator("scope", mode="before")
    @classmethod
    def _scope(cls, v):
        if v == "report":
            raise ValueError("scope 'report' is not supported yet; "
                             "criteria match on any of the patient's in-population reports")
        return v

    reject_deferred = field_validator("criteria", mode="before")(_reject_deferred_all)

    @model_validator(mode="after")
    def _check(self):
        ids = [c.id for c in self.criteria]
        for i in ids:
            if i is None or not ID_RE.match(i):
                raise ValueError(f"criteria: every criterion needs an id like 'c1', not {i!r}")
        if len(set(ids)) != len(ids):
            raise ValueError("criteria: duplicate criterion id")
        for c in self.criteria:
            if c.kind == "any_of" and any(m.id is not None for m in c.of):
                raise ValueError(f"criteria.{c.id}: any_of members take no id")
        if len(set(self.breakdown)) != len(self.breakdown):
            raise ValueError("breakdown: duplicate dimension")
        if self.pivot:
            self._check_pivot(self.pivot)
        return self

    def _check_pivot(self, pivot: Pivot) -> None:
        if pivot.rows == pivot.cols:
            raise ValueError("pivot: rows and cols must differ")
        by_id = {c.id: c for c in self.criteria}
        for field, axis in (("rows", pivot.rows), ("cols", pivot.cols)):
            if axis in PIVOT_DIMS:
                continue
            m = AXIS_RE.match(axis)
            if not m:
                raise ValueError(f"pivot.{field}: '{axis}' is not a dimension or a criterion axis like 'c1.key'")
            if m[1] not in by_id:
                raise ValueError(f"pivot.{field}: unknown criterion '{m[1]}'")
            if _has_specimen(by_id[m[1]]):
                raise ValueError(f"pivot.{field}: a specimen criterion cannot be a pivot axis")


def parse(data: dict) -> Definition:
    """Definition.model_validate(data), with ValidationError re-raised as DefinitionError."""
    try:
        return Definition.model_validate(data)
    except ValidationError as e:
        raise _error(e) from None


def cohort_id(d: Definition) -> str:
    """Stable id of what selects patients: version, scope, population and criteria (not the
    name, breakdown, pivot, criterion ids or criterion order)."""
    canonical = json.dumps(
        {"version": d.version, "scope": d.scope,
         "population": d.population.model_dump(mode="json", exclude_defaults=True),
         "criteria": sorted((_canon(c) for c in d.criteria), key=lambda c: json.dumps(c, sort_keys=True))},
        sort_keys=True, separators=(",", ":"))
    return f"v{SCHEMA_VERSION}-{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


def json_schema() -> dict:
    return Definition.model_json_schema(by_alias=True)


# --- data notes ----------------------------------------------------------------------------------

NOTES = {
    "age": "Age is known for Caris tissue reports only; everything else is 'unknown'.",
    "ihc": "IHC results are Caris only, so FMI patients cannot match an IHC criterion.",
    "expression": "Expression percentiles come from Caris whole-transcriptome reports only.",
    "specimen": "Specimen site and type are Caris only, from the report's first tumor specimen.",
    "has_wts": "has_wts is Caris only; FMI reports are always 'false'.",
    "fda": "FMI's FDA flag means approved in any indication, not necessarily in this tumor type.",
    "absent": "Stage, treatment, outcomes, race and ethnicity are not in this data.",
}


def data_notes(d: Definition) -> list[str]:
    """The caveats that apply to this definition: a pure function of it. `absent` always last."""
    leaves = [m for c in d.criteria for m in (c.of if c.kind == "any_of" else [c])]
    axes = {d.pivot.rows, d.pivot.cols} if d.pivot else set()
    uses = lambda dim: dim in d.breakdown or dim in axes   # noqa: E731
    on = {
        "age": bool(d.population.age_band) or uses("age_band"),
        "ihc": any(m.kind == "ihc" for m in leaves),
        "expression": any(m.kind == "expression" for m in leaves),
        "specimen": any(m.kind == "specimen" and (m.site_type or m.site) for m in leaves) or uses("site_type"),
        "has_wts": uses("has_wts"),
        "fda": any(m.kind == "actionability" and "fmi_fda_any_indication" in m.evidence for m in leaves),
    }
    return [NOTES[k] for k, v in on.items() if v] + [NOTES["absent"]]


# --- operations ----------------------------------------------------------------------------------

class _Op(BaseModel):
    model_config = _CONFIG


class AddCriterion(_Op):
    op: Literal["add_criterion"]
    criterion: Criterion
    reject_deferred = field_validator("criterion", mode="before")(_reject_deferred)


class RemoveCriterion(_Op):
    op: Literal["remove_criterion"]
    id: str


class UpdateCriterion(_Op):
    op: Literal["update_criterion"]
    id: str
    criterion: Criterion
    reject_deferred = field_validator("criterion", mode="before")(_reject_deferred)


class SetPopulation(_Op):
    op: Literal["set_population"]
    population: Population


class SetBreakdown(_Op):
    op: Literal["set_breakdown"]
    breakdown: list[BreakdownDim]


class SetPivot(_Op):
    op: Literal["set_pivot"]
    pivot: Pivot | None


class Rename(_Op):
    op: Literal["rename"]
    name: str


Operation = Annotated[AddCriterion | RemoveCriterion | UpdateCriterion | SetPopulation | SetBreakdown
                      | SetPivot | Rename, Field(discriminator="op")]
_OPERATION = TypeAdapter(Operation)


def operation_json_schema() -> dict:
    return _OPERATION.json_schema(by_alias=True)


def apply(d: Definition, op: "Operation | dict", vocab=None) -> Definition:
    """Return `d` with `op` applied, re-validated (and checked against `vocab` when given).
    `d` is never changed. Any failure raises DefinitionError."""
    try:
        o = _OPERATION.validate_python(op)
        data = d.model_dump(mode="json", by_alias=True)
        criteria = data["criteria"]
        position = {c["id"]: i for i, c in enumerate(criteria)}
        match o:
            case AddCriterion():
                new = o.criterion.model_dump(mode="json", by_alias=True)
                if new["id"] is None:
                    new["id"] = f"c{max((int(i[1:]) for i in position), default=0) + 1}"
                elif new["id"] in position:
                    raise DefinitionError(f"criterion id '{new['id']}' already exists")
                criteria.append(new)
            case RemoveCriterion() | UpdateCriterion():
                if o.id not in position:
                    raise DefinitionError(f"unknown criterion id '{o.id}'")
                if isinstance(o, UpdateCriterion):
                    criteria[position[o.id]] = o.criterion.model_dump(mode="json", by_alias=True) | {"id": o.id}
                else:
                    del criteria[position[o.id]]
                    pivot = data["pivot"]
                    if pivot and any(a.startswith(f"{o.id}.") for a in (pivot["rows"], pivot["cols"])):
                        data["pivot"] = None
            case SetPopulation():
                data["population"] = o.population.model_dump(mode="json", by_alias=True)
            case SetBreakdown():
                data["breakdown"] = list(o.breakdown)
            case SetPivot():
                data["pivot"] = o.pivot.model_dump(mode="json") if o.pivot else None
            case Rename():
                data["name"] = o.name
        new_d = Definition.model_validate(data)
    except ValidationError as e:
        raise _error(e) from None
    if vocab is not None:
        vocab.check(new_d)
    return new_d
