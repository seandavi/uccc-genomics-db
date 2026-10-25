import os

from uccc_genomics.config import DEID_DB


def deid_lacks_tier():
    """True while the real de-id file predates `unified.variant.tier` (#32), until the next daily rebuild.

    Real-DB tests skip then instead of failing; synthetic tests cover the columns meanwhile.
    """
    if not os.path.exists(DEID_DB):
        return False
    from uccc_genomics_mcp import server
    con = server.get_db()
    try:
        return "tier" not in {r[0] for r in con.execute("DESCRIBE unified.variant").fetchall()}
    finally:
        con.close()
