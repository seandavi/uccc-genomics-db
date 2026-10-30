"""Run a cohort definition against the de-identified file: the only code here that opens a connection.

Results are typed and suppressed (`suppress.py`); nothing row-level comes back.
"""
import datetime
import os

import duckdb

from uccc_genomics_mcp.server import DEID_DB, get_db

from .compile import compile, compile_pivot
from .definition import Definition, DefinitionError, apply, neighbours
from .suppress import (MIN_CELL, CountResult, PivotResult, RawCount, RawNeighbour, RawPivot, RawPivotNeighbour,
                       floor, suppress_count, suppress_pivot)
from .vocabulary import VOCAB_SQL, VocabEntry, Vocabulary

_vocab = {"mtime": None, "v": None}


def vocabulary() -> Vocabulary:
    """The floored vocabulary, rebuilt when the daily rebuild replaces the file."""
    mtime = os.path.getmtime(DEID_DB)
    if _vocab["mtime"] != mtime:
        con = get_db()
        try:
            entries = [VocabEntry(field=f, parent=p, value=v, patients=floor(n))
                       for f, p, v, n in con.execute(VOCAB_SQL).fetchall()]
            years = con.execute("SELECT min(year), max(year) FROM mart.report").fetchone()
        finally:
            con.close()
        _vocab["v"] = Vocabulary(entries=entries, years=tuple(years) if years and years[0] is not None else None)
        _vocab["mtime"] = mtime
    return _vocab["v"]


def snapshot_id() -> str | None:
    """The de-id build's id (meta.build, written by deid), or None for a file built before #132."""
    con = get_db()
    try:
        row = con.execute("SELECT build_id FROM meta.build").fetchone()
    except duckdb.CatalogException:
        return None
    finally:
        con.close()
    return row[0] if row else None


def data_date() -> datetime.date:
    """The local date the daily rebuild last wrote the de-id file (its mtime): a snapshot's data date."""
    return datetime.date.fromtimestamp(os.path.getmtime(DEID_DB))


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
    near = neighbours(d)   # raises (a 400) before any query
    con = get_db()
    try:
        raw = _run_count(con, d)
        raw.neighbours = [RawNeighbour(_run_count(con, n.definition), n.step) for n in near]
        result = suppress_count(d, raw)
        if not near and (result.patients is None or raw.funnel[-1] < MIN_CELL):
            for c in d.criteria:
                without = apply(d, {"op": "remove_criterion", "id": c.id})
                raw.loosen[c.id] = _run_count(con, without).funnel[-1]
            result = suppress_count(d, raw)
        return result
    finally:
        con.close()


def _run_pivot(con, d: Definition) -> RawPivot:
    sql, params = compile_pivot(d)
    rows = con.execute(sql, params).fetchall()
    raw = RawPivot(funnel=_funnel(rows), cells={}, rows={}, cols={})
    for section, r, c, patients in (row[:4] for row in rows):
        if section == "cell":
            raw.cells[(r, c)] = patients
        elif section == "row":
            raw.rows[r] = patients
        elif section == "col":
            raw.cols[c] = patients
    return raw


def pivot(d: Definition) -> PivotResult:
    if d.pivot is None:
        raise DefinitionError("pivot: the definition has no pivot")
    vocabulary().check(d)
    near = neighbours(d)
    con = get_db()
    try:
        raw = _run_pivot(con, d)
        raw.neighbours = [RawPivotNeighbour(_run_pivot(con, n.definition), n.step) for n in near]
    finally:
        con.close()
    return suppress_pivot(d, raw)
