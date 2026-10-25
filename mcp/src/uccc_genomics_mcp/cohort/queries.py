"""Run a cohort definition against the de-identified file: the only code here that opens a connection.

Results are typed and suppressed (`suppress.py`); nothing row-level comes back.
"""
import os

from uccc_genomics_mcp.server import DEID_DB, get_db

from .compile import compile, compile_pivot
from .definition import Definition, DefinitionError, apply
from .suppress import (MIN_CELL, CountResult, PivotResult, RawCount, RawPivot, floor, suppress_count,
                       suppress_pivot)
from .vocabulary import VOCAB_SQL, VocabEntry, Vocabulary

_vocab = {"mtime": None, "v": None}


def vocabulary() -> Vocabulary:
    """The floored vocabulary, rebuilt when the daily rebuild replaces the file."""
    mtime = os.path.getmtime(DEID_DB)
    if _vocab["mtime"] != mtime:
        con = get_db()
        try:
            # A child's count would let a parent's count minus its shown children recover a floored-out child.
            entries = [VocabEntry(field=f, parent=p, value=v, patients=floor(n) if p is None else None)
                       for f, p, v, n in con.execute(VOCAB_SQL).fetchall()]
            years = con.execute("SELECT min(year), max(year) FROM mart.report").fetchone()
        finally:
            con.close()
        _vocab["v"] = Vocabulary(entries=entries, years=tuple(years) if years and years[0] is not None else None)
        _vocab["mtime"] = mtime
    return _vocab["v"]


def _funnel(rows: list[tuple]) -> list[int]:
    return [int(r[3]) for r in sorted((r for r in rows if r[0] == "funnel"), key=lambda r: int(r[1]))]


def _run_count(con, d: Definition) -> RawCount:
    sql, params = compile(d)
    rows = con.execute(sql, params).fetchall()
    raw = RawCount(funnel=_funnel(rows), reports=0, by_year={}, year_complete={}, breakdowns={}, denominators={})
    for section, dim, value, patients, flag in rows:
        if section == "reports":
            raw.reports = patients
        elif section == "year":
            raw.by_year[int(value)] = patients
        elif section == "year_complete":
            raw.year_complete[int(value)] = flag
        elif section == "breakdown":
            raw.breakdowns.setdefault(dim, {})[value] = patients
        elif section == "denominator":
            raw.denominators.setdefault(dim, {})[value] = patients
    return raw


def count(d: Definition) -> CountResult:
    vocabulary().check(d)
    con = get_db()
    try:
        raw = _run_count(con, d)
        result = suppress_count(d, raw)
        if result.patients is None or raw.funnel[-1] < MIN_CELL:
            for c in d.criteria:
                without = apply(d, {"op": "remove_criterion", "id": c.id})
                raw.loosen[c.id] = _run_count(con, without).funnel[-1]
            result = suppress_count(d, raw)
        return result
    finally:
        con.close()


def pivot(d: Definition) -> PivotResult:
    if d.pivot is None:
        raise DefinitionError("pivot: the definition has no pivot")
    vocabulary().check(d)
    sql, params = compile_pivot(d)
    con = get_db()
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    raw = RawPivot(funnel=_funnel(rows), cells={}, rows={}, cols={})
    for section, r, c, patients in (row[:4] for row in rows):
        if section == "cell":
            raw.cells[(r, c)] = patients
        elif section == "row":
            raw.rows[r] = patients
        elif section == "col":
            raw.cols[c] = patients
    return suppress_pivot(d, raw)
