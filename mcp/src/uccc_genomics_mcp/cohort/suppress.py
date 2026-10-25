"""Small-cell suppression for cohort results (COHORT_DISCOVERY.md §3.6).

Raw counts go in, `CountResult` / `PivotResult` come out. Every number in a result has been
through `floor`, the neighbour check, the secondary-suppression line rule, the funnel delta rule
and the whole-cohort rule, so nothing from 1 to 4 and nothing recoverable by subtraction within
one list, one pivot or one funnel, or against the same cohort one edit away (without an exclusion,
with tested_negative as a plain exclusion, without a population value or an end year, at patient scope
instead of report scope: `neighbours`),
leaves this module. A breakdown cell and its
population denominator are nested sets whose difference is shown on purpose (it is the
percentage). Not covered, and accepted under the audit log (spec rule 3, COHORT_DISCOVERY.md
§3.6): OR lists inside a criterion, differencing that combines three or more queries, and that
breakdown cell against its denominator.
"""
import os
from dataclasses import dataclass, field

from pydantic import BaseModel

import uccc_genomics.config  # noqa: F401  loads the repo .env (COHORT_ROUND)
from .definition import Definition, cohort_id, data_notes, neighbours

MIN_CELL = 5
ROUND = int(os.environ.get("COHORT_ROUND", "1"))  # 5 rounds every cleared count to the nearest 5 (open question 1)


def floor(n):
    if n is None or n == 0:
        return n
    if n < MIN_CELL:
        return None
    return max(MIN_CELL, ROUND * round(n / ROUND))


# --- raw inputs (never returned by a public function) -------------------------------------------

@dataclass
class RawNeighbour:
    raw: "RawCount"
    step: list[int]                         # step[k]: this neighbour's funnel index that pairs with step k


@dataclass
class RawPivotNeighbour:
    raw: "RawPivot"
    step: list[int]


@dataclass
class RawCount:
    funnel: list[int]                       # step 0 = population, step k = after criterion k
    reports: int
    by_year: dict[int, int]                 # first-qualifying year -> patients
    year_complete: dict[int, bool]
    breakdowns: dict[str, dict[str, int]]   # dim -> value -> patients (hit)
    denominators: dict[str, dict[str, int]] # dim -> value -> patients (pop)
    loosen: dict[str, int] = field(default_factory=dict)   # criterion id -> raw count without it (only when computed)
    neighbours: list[RawNeighbour] = field(default_factory=list)   # one per `neighbours(d)`, in order


@dataclass
class RawPivot:
    funnel: list[int]
    cells: dict[tuple[str, str], int]
    rows: dict[str, int]
    cols: dict[str, int]
    neighbours: list[RawPivotNeighbour] = field(default_factory=list)


# --- results (the only shapes that leave the module) ---------------------------------------------

class FunnelStep(BaseModel):
    criterion: str | None       # None = the population
    patients: int | None


class YearCount(BaseModel):
    year: int
    patients: int | None
    complete: bool


class BreakdownCell(BaseModel):
    value: str
    patients: int | None
    denominator: int | None


class Loosen(BaseModel):
    drop: str
    patients: int


class CountResult(BaseModel):
    cohort_id: str
    patients: int | None
    reports: int | None
    denominator: int | None
    funnel: list[FunnelStep]
    by_year: list[YearCount]
    breakdowns: dict[str, list[BreakdownCell]]
    notes: list[str]
    loosen: list[Loosen]
    loosen_offered: bool = True     # False when the definition has neighbours: a suggestion would need its own checks
    min_cell: int = MIN_CELL


class PivotCell(BaseModel):
    row: str
    col: str
    patients: int | None


class Margin(BaseModel):
    value: str
    patients: int | None


class PivotResult(BaseModel):
    cohort_id: str
    rows: str
    cols: str
    patients: int | None
    cells: list[PivotCell]
    row_totals: list[Margin]
    col_totals: list[Margin]
    notes: list[str]
    min_cell: int = MIN_CELL


# --- rules ----------------------------------------------------------------------------------------

def _near(a: int, b: int) -> bool:
    """Two counts 1..4 apart: shown together they reveal the difference, a small count."""
    return 0 < abs(a - b) < MIN_CELL


def _funnel(raw: list[int], hidden: frozenset[int] | set[int] = frozenset()) -> list[int | None]:
    """Floor every step, and hide a step whose drop from the last shown step is 1..4: the
    difference of two adjacent steps is a count too. [20, 18, 10, 9, 3] -> [20, None, 10, None, None].
    Steps in `hidden` (the neighbour check) are None and are not a last shown step."""
    out, last = [], None
    for k, n in enumerate(raw):
        shown = None if k in hidden or (last is not None and 0 < last - n < MIN_CELL) else floor(n)
        out.append(shown)
        if shown is not None:
            last = n
    return out


def _line(values: list[int | None], total: int | None) -> list[int | None]:
    """Secondary suppression: a line (cells plus its total) with exactly one hidden value would
    let the hidden one be recovered by subtraction, so hide the smallest shown positive cell too
    (ties: first in line order). The total is never a candidate; zeros are known and never chosen."""
    if sum(v is None for v in [*values, total]) != 1:
        return values
    shown = [i for i, v in enumerate(values) if v]
    if not shown:
        return values
    out = list(values)
    out[min(shown, key=lambda i: (values[i], i))] = None
    return out


def _suppress_line(cells: dict, keys: list, total, unlisted_small: bool = False) -> None:
    """Apply `_line` to `cells[k] for k in keys` in place. `unlisted_small`: patients that belong
    in this line were left out of it and could be 1..4, so they count as one more hidden value."""
    new = _line([cells[k] for k in keys] + [None] * unlisted_small, total)
    cells.update(zip(keys, new))


def _check_neighbours(d: Definition, raw) -> None:
    if len(raw.neighbours) != len(neighbours(d)):
        raise ValueError("raw.neighbours does not match neighbours(d)")


def _hidden_steps(raw) -> set[int]:
    return {k for k, n in enumerate(raw.funnel) for nb in raw.neighbours if _near(n, nb.raw.funnel[nb.step[k]])}


def suppress_count(d: Definition, raw: RawCount) -> CountResult:
    _check_neighbours(d, raw)
    steps = _funnel(raw.funnel, _hidden_steps(raw))
    patients, denominator = steps[-1], steps[0]
    funnel = [FunnelStep(criterion=cid, patients=n)
              for cid, n in zip([None, *(c.id for c in d.criteria)], steps)]
    by_year, breakdowns, reports = [], {dim: [] for dim in d.breakdown}, None
    if patients is not None:
        near = lambda value, of: any(_near(value, of(nb.raw)) for nb in raw.neighbours)   # noqa: E731
        reports = None if near(raw.reports, lambda r: r.reports) else floor(raw.reports)
        years = {y: None if near(n, lambda r, y=y: r.by_year.get(y, 0)) else floor(n)
                 for y, n in sorted(raw.by_year.items())}
        # Patients with no dated report are in `patients` but in no year.
        undated = raw.funnel[-1] - sum(raw.by_year.values())
        _suppress_line(years, list(years), patients, 0 < undated < MIN_CELL)
        by_year = [YearCount(year=y, patients=n, complete=raw.year_complete.get(y, True))
                   for y, n in years.items()]
        for dim in d.breakdown:
            values = sorted(raw.breakdowns.get(dim, {}))
            cells = {v: None if near(raw.breakdowns[dim][v], lambda r, v=v: r.breakdowns.get(dim, {}).get(v, 0))
                     else floor(raw.breakdowns[dim][v]) for v in values}
            dens = {v: None if near(raw.denominators.get(dim, {}).get(v, 0),
                                    lambda r, v=v: r.denominators.get(dim, {}).get(v, 0))
                    else floor(raw.denominators.get(dim, {}).get(v, 0)) for v in values}
            _suppress_line(cells, values, patients)
            # Population values with no cohort patients are not listed. If every one is under MIN_CELL
            # they are 1..4 patients in all, a hidden value; one of MIN_CELL or more keeps them above that.
            unlisted = [n for v, n in raw.denominators.get(dim, {}).items() if v not in values]
            _suppress_line(dens, values, denominator, bool(unlisted) and max(unlisted) < MIN_CELL)
            # Sorted after suppression, so the order says nothing about hidden values.
            breakdowns[dim] = sorted((BreakdownCell(value=v, patients=cells[v], denominator=dens[v])
                                      for v in values),
                                     key=lambda c: (c.patients is None, -(c.patients or 0), c.value))
    loosen = []
    if not raw.neighbours and (patients is None or raw.funnel[-1] < MIN_CELL):
        for cid, n in raw.loosen.items():
            # A suggestion is a set nested in every earlier funnel step. Shown next to a shown step 1..4
            # away, or equal to a step the funnel rule hid, it would reveal what that rule hid.
            clear = all(n != s if shown is None else abs(s - n) >= MIN_CELL or s == n
                        for s, shown in zip(raw.funnel, steps))
            if floor(n) is not None and n - raw.funnel[-1] >= MIN_CELL and clear:
                loosen.append(Loosen(drop=cid, patients=floor(n)))
        loosen.sort(key=lambda s: (-s.patients, s.drop))
    return CountResult(cohort_id=cohort_id(d), patients=patients, reports=reports, denominator=denominator,
                       funnel=funnel, by_year=by_year, breakdowns=breakdowns, notes=data_notes(d), loosen=loosen,
                       loosen_offered=not raw.neighbours)


def _raw_value(raw: RawPivot, key: tuple) -> int:
    match key:
        case ("cell", r, c):
            return raw.cells.get((r, c), 0)
        case ("row", r):
            return raw.rows[r]
        case _:
            return raw.cols[key[1]]


def suppress_pivot(d: Definition, raw: RawPivot) -> PivotResult:
    assert d.pivot is not None
    _check_neighbours(d, raw)
    patients = _funnel(raw.funnel, _hidden_steps(raw))[-1]
    cells, row_totals, col_totals = [], [], []
    if patients is not None:
        rows, cols = sorted(raw.rows), sorted(raw.cols)
        val = {("cell", r, c): floor(raw.cells.get((r, c), 0)) for r in rows for c in cols}
        val |= {("row", r): floor(raw.rows[r]) for r in rows} | {("col", c): floor(raw.cols[c]) for c in cols}
        lines = ([([("cell", r, c) for c in cols], ("row", r)) for r in rows]
                 + [([("cell", r, c) for r in rows], ("col", c)) for c in cols]
                 + [([("row", r) for r in rows], ("total",)), ([("col", c) for c in cols], ("total",))])
        val[("total",)] = patients
        for nb in raw.neighbours:   # the neighbour check on cells and margins, before the line rules
            n = nb.raw
            for key, other in ([(("cell", r, c), n.cells.get((r, c), 0)) for r in rows for c in cols]
                               + [(("row", r), n.rows.get(r, 0)) for r in rows]
                               + [(("col", c), n.cols.get(c, 0)) for c in cols]):
                if val[key] is not None and _near(_raw_value(raw, key), other):
                    val[key] = None
        def step() -> bool:
            changed = False
            for keys, total in lines:
                old = [val[k] for k in keys]
                new = _line(old, val[total])
                if new == old and total != ("total",) and val[total] is not None and old.count(None) == 1:
                    # Nothing shown is left to hide with the single hidden cell: it equals the line total.
                    new, val[total], changed = old, None, True
                if new != old:
                    val.update(zip(keys, new))
                    changed = True
            return changed

        # Hiding one value can leave another line with a single hidden value: repeat to a fixed point.
        while step():
            pass
        cells = [PivotCell(row=r, col=c, patients=val[("cell", r, c)]) for (r, c) in sorted(raw.cells)]
        row_totals = [Margin(value=r, patients=val[("row", r)]) for r in rows]
        col_totals = [Margin(value=c, patients=val[("col", c)]) for c in cols]
    return PivotResult(cohort_id=cohort_id(d), rows=d.pivot.rows, cols=d.pivot.cols, patients=patients,
                       cells=cells, row_totals=row_totals, col_totals=col_totals, notes=data_notes(d))
