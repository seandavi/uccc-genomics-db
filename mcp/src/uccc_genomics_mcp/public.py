"""The public landing page's totals (docs/specs/41-*.md): fixed, unfilterable aggregates over mart.report,
each floored at MIN_CELL and rounded to the nearest PUBLIC_ROUND. No parameters reach SQL."""
import os

from pydantic import BaseModel

from uccc_genomics_mcp.cohort.suppress import MIN_CELL, YearCount
from uccc_genomics_mcp.server import DEID_DB, get_db

PUBLIC_ROUND = 10


class PublicSummary(BaseModel):
    patients: int | None      # distinct research_id; null = under MIN_CELL
    reports: int | None       # rows of mart.report
    tumor_types: int | None   # oncotree codes (not NULL, not 'OTHER') with >= MIN_CELL patients
    vendors: list[str]        # vendor values with >= MIN_CELL patients, sorted ("caris", "fmi")
    first_year: int | None    # first / last year in by_year
    last_year: int | None
    by_year: list[YearCount]  # patients by year of their first sample, first_year..last_year
    min_cell: int             # MIN_CELL: the landing page shows null as "<5"
    round_to: int             # PUBLIC_ROUND: the landing page says counts are rounded to it


def coarse(n: int) -> int | None:
    """None under MIN_CELL (0 included), else n to the nearest PUBLIC_ROUND, halves up, so never under 10."""
    return None if n < MIN_CELL else (n + PUBLIC_ROUND // 2) // PUBLIC_ROUND * PUBLIC_ROUND


_summary = {"mtime": None, "v": None}


def _compute() -> PublicSummary:
    con = get_db()
    try:
        patients, reports = con.execute("SELECT count(DISTINCT research_id), count(*) FROM mart.report").fetchone()
        tumor_types = con.execute(
            "SELECT count(*) FROM (SELECT oncotree FROM mart.report "
            "WHERE oncotree IS NOT NULL AND oncotree <> 'OTHER' "
            "GROUP BY oncotree HAVING count(DISTINCT research_id) >= $min_cell)", {"min_cell": MIN_CELL}).fetchone()[0]
        vendors = [v for (v,) in con.execute(
            "SELECT vendor FROM mart.report GROUP BY vendor "
            "HAVING count(DISTINCT research_id) >= $min_cell ORDER BY vendor", {"min_cell": MIN_CELL}).fetchall()]
        # first-sample year per patient, as Discover's accrual (compile.py `pp`); complete as compile.py's year_complete row
        years = con.execute(
            "WITH pp AS (SELECT research_id, min(year) AS yr FROM mart.report WHERE year IS NOT NULL GROUP BY 1), "
            "c AS (SELECT year, bool_and(year_complete) AS complete FROM mart.report "
            "WHERE year IS NOT NULL GROUP BY 1) "
            "SELECT pp.yr, count(*), c.complete FROM pp JOIN c ON c.year = pp.yr GROUP BY 1, 3 ORDER BY 1").fetchall()
    finally:
        con.close()
    big = [y for y, n, _ in years if n >= MIN_CELL]   # a date-shifted outlier year never appears, not even as "<5"
    first, last = (min(big), max(big)) if big else (None, None)
    return PublicSummary(
        patients=coarse(patients), reports=coarse(reports), tumor_types=coarse(tumor_types), vendors=vendors,
        first_year=first, last_year=last,
        by_year=[YearCount(year=y, patients=coarse(n), complete=bool(c)) for y, n, c in years
                 if first is not None and first <= y <= last],
        min_cell=MIN_CELL, round_to=PUBLIC_ROUND)


def summary() -> PublicSummary:
    """Computed once per de-id file (keyed on its mtime, like queries.vocabulary)."""
    mtime = os.path.getmtime(DEID_DB)
    if _summary["mtime"] != mtime:
        _summary["v"] = _compute()
        _summary["mtime"] = mtime
    return _summary["v"]
