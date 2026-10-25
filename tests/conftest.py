import os

import duckdb

from uccc_genomics.config import DEID_DB


def deid_lacks_tier():
    """True while the real de-id file predates `unified.variant.tier` (#32), until the next daily rebuild.

    Real-DB tests skip then instead of failing; synthetic tests cover the columns meanwhile. Runs at
    collection time (inside skipif), so a file that can't be opened (e.g. mid-rebuild) returns False:
    the real-DB tests then fail on their own, and collection of the synthetic tests isn't affected.
    """
    if not os.path.exists(DEID_DB):
        return False
    from uccc_genomics_mcp import server
    try:
        con = server.get_db()
        try:
            return "tier" not in {r[0] for r in con.execute("DESCRIBE unified.variant").fetchall()}
        finally:
            con.close()
    except (duckdb.Error, OSError):
        return False


def deid_lacks_mart():
    """True while the real de-id file has no `mart.fact` (#33) or no `mart.report.collected_on` (#38),
    until the next daily rebuild.

    Same collection-time guard as `deid_lacks_tier`: a file that can't be opened returns False.
    """
    if not os.path.exists(DEID_DB):
        return False
    from uccc_genomics_mcp import server
    try:
        con = server.get_db()
        try:
            return not con.execute("SELECT 1 FROM information_schema.columns "
                                   "WHERE table_schema = 'mart' AND table_name = 'report' "
                                   "AND column_name = 'collected_on'").fetchall() or not con.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = 'fact'").fetchall()
        finally:
            con.close()
    except (duckdb.Error, OSError):
        return False
