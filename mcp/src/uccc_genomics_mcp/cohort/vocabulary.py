"""Floored vocabulary of the values a cohort definition may name (typeahead and validation).

A value held by fewer than MIN_CELL patients is never offered, so it cannot be OR-ed into a
larger value and recovered by differencing.
"""
from functools import cached_property

from pydantic import BaseModel, Field

from .definition import CUT_POINTS, POP_DIMS, Definition, DefinitionError
from .suppress import MIN_CELL

# mart.fact without benign mutation rows (they are kept in the mart; the tier filter hides them).
_F = ("(SELECT * FROM mart.fact WHERE NOT (kind = 'alteration' AND sub = 'mutation' "
      "AND tier IS NOT DISTINCT FROM 'likely_benign_or_benign'))")

VOCAB_SQL = f"""
SELECT field, parent, value, patients FROM (
  SELECT field, parent, value, count(DISTINCT research_id) AS patients FROM (
    {" UNION ALL ".join(f"SELECT 'population.{d}' AS field, NULL AS parent, {d} AS value, research_id FROM mart.report WHERE {d} IS NOT NULL" for d in POP_DIMS)}
    UNION ALL SELECT 'alteration.gene', NULL, upper(key), research_id FROM {_F} WHERE kind = 'alteration'
    UNION ALL SELECT 'alteration.aa', upper(key), val, research_id FROM {_F}
      WHERE kind = 'alteration' AND sub = 'mutation' AND val IS NOT NULL
    UNION ALL SELECT 'biomarker.call', key, val, research_id FROM {_F} WHERE kind = 'biomarker' AND val IS NOT NULL
    UNION ALL SELECT 'ihc.marker', NULL, key, research_id FROM {_F} WHERE kind = 'ihc'
    UNION ALL SELECT 'ihc.clone', key, sub, research_id FROM {_F} WHERE kind = 'ihc' AND sub IS NOT NULL
    UNION ALL SELECT 'ihc.call', key, val, research_id FROM {_F} WHERE kind = 'ihc' AND val IS NOT NULL
    UNION ALL SELECT 'expression.gene', NULL, upper(key), research_id FROM {_F} WHERE kind = 'expression'
    UNION ALL SELECT 'specimen.site_type', NULL, val, research_id FROM {_F} WHERE kind = 'specimen' AND key = 'site_type'
    UNION ALL SELECT 'specimen.site', NULL, val, research_id FROM {_F} WHERE kind = 'specimen' AND key = 'site'
    UNION ALL SELECT 'actionability.evidence', NULL, key, research_id FROM {_F} WHERE kind = 'actionability'
  ) GROUP BY 1, 2, 3
) WHERE patients >= {MIN_CELL}
"""


class VocabEntry(BaseModel):
    field: str            # e.g. "population.oncotree", "alteration.aa"
    parent: str | None    # alteration.aa -> gene; biomarker.call -> name; ihc.clone/ihc.call -> marker
    value: str
    # floor()ed, >= MIN_CELL; ranks `search` only and is never serialised: any shown count lets a
    # nested pair (a parent and its children, organ and oncotree) give back a floored-out value.
    patients: int = Field(exclude=True)


class Vocabulary(BaseModel):
    entries: list[VocabEntry]
    years: tuple[int, int] | None          # min/max mart.report.year; None on an empty mart
    cut_points: dict[str, list[float]] = CUT_POINTS
    min_cell: int = MIN_CELL

    @cached_property
    def by_field(self) -> dict[tuple[str, str | None], set[str]]:
        index: dict[tuple[str, str | None], set[str]] = {}
        for e in self.entries:
            index.setdefault((e.field, None), set()).add(e.value)       # any parent
            if e.parent is not None:
                index.setdefault((e.field, e.parent), set()).add(e.value)
        return index

    def allowed(self, field: str, parent: str | None = None) -> set[str]:
        return self.by_field.get((field, parent), set())

    def check(self, d: Definition) -> None:
        """Raise DefinitionError naming the field and the first value the vocabulary does not hold."""
        def need(path: str, field: str, values, parent: str | None = None):
            ok = self.allowed(field, parent)
            for v in values:
                if v not in ok:
                    of = f" for {parent}" if parent else ""
                    raise DefinitionError(f"{path}: {v!r} is not in the vocabulary{of}")

        for dim in POP_DIMS:
            need(f"population.{dim}", f"population.{dim}", getattr(d.population, dim))
        if d.population.years is not None:
            lo, hi = d.population.years
            if self.years is None or lo < self.years[0] or hi > self.years[1]:
                raise DefinitionError(f"population.years: {list(d.population.years)} is outside the data's years "
                                      f"{list(self.years) if self.years else 'none'}")
        for c in d.criteria:
            for j, m in enumerate(c.of if c.kind == "any_of" else [c]):
                p = f"criteria.{c.id}" + (f".of.{j}" if c.kind == "any_of" else "")
                match m.kind:
                    case "alteration":
                        need(f"{p}.gene", "alteration.gene", m.gene)
                        need(f"{p}.aa", "alteration.aa", m.aa, m.gene[0])
                    case "biomarker":
                        need(f"{p}.call", "biomarker.call", m.call, m.name)
                    case "ihc":
                        need(f"{p}.marker", "ihc.marker", [m.marker])
                        need(f"{p}.clone", "ihc.clone", [m.clone] if m.clone else [], m.marker)
                        need(f"{p}.call", "ihc.call", m.call, m.marker)
                    case "expression":
                        need(f"{p}.gene", "expression.gene", m.gene)
                    case "specimen":
                        need(f"{p}.site_type", "specimen.site_type", m.site_type)
                        need(f"{p}.site", "specimen.site", m.site)
                    case "actionability":
                        need(f"{p}.evidence", "actionability.evidence", m.evidence)

    def search(self, q: str, limit: int = 20) -> list[VocabEntry]:
        q = q.strip().lower()
        if not q or len(q) > 100:
            return []
        limit = max(1, min(limit, 50))

        def rank(e: VocabEntry):
            v = e.value.lower()
            return (v != q, not v.startswith(q), -e.patients, e.value)

        return sorted((e for e in self.entries if q in e.value.lower()), key=rank)[:limit]

