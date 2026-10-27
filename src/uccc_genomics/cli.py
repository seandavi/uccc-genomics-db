"""genomics — sync raw vendor files, load them, de-identify.

  genomics sync  [--vendor caris|fmi]
  genomics load  [--vendor caris|fmi]
  genomics deid
  genomics all                      # sync + load for every vendor, then deid
  genomics check [--vendor caris|fmi]   # exit non-zero if a vendor's newest received date is older than STALE_DAYS (default 21)
  genomics shell [--phi]            # duckdb CLI with the (encrypted) de-id file attached; --phi for the PHI file
"""
import argparse
import os
import sys
import time
from datetime import date

from . import caris, deid, fmi
from .config import DATA, DEID_DB, DEID_DB_KEY, PHI_DB, PHI_DB_KEY, STALE_DAYS, connect, read_key

VENDORS = {"caris": caris, "fmi": fmi}

# Newest received date per vendor, from the PHI file (de-id dates are shifted per patient).
NEWEST_RECEIVED = {"caris": "SELECT max(received_at)::DATE FROM phi.caris.report",
                   "fmi": "SELECT max(received_on) FROM phi.fmi.report"}


def check(vendors: list[str]) -> None:
    """Exit non-zero naming every vendor whose newest received date is older than STALE_DAYS."""
    con = connect(phi=(PHI_DB, PHI_DB_KEY, "READ_ONLY"))
    stale = []
    for v in vendors:
        newest = con.execute(NEWEST_RECEIVED[v]).fetchone()[0]
        age = (date.today() - newest).days if newest else None
        print(f"== check {v}: newest received date is {age} days old (limit {STALE_DAYS})", file=sys.stderr)
        if age is None or age > STALE_DAYS:
            stale.append(v)
    con.close()
    if stale:
        sys.exit(f"stale vendor data: {', '.join(stale)} (newest received date older than {STALE_DAYS} days)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="genomics", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["sync", "load", "deid", "all", "check", "shell"])
    p.add_argument("--vendor", choices=list(VENDORS), help="default: every vendor")
    p.add_argument("--phi", action="store_true", help="shell: open the identified file instead")
    a = p.parse_args(argv)
    if a.step == "shell":
        path, keyfile, alias = (PHI_DB, PHI_DB_KEY, "phi") if a.phi else (DEID_DB, DEID_DB_KEY, "db")
        init = f"{DATA}/.duckdb_init_{alias}"  # mode 600 next to the keys; avoids the key in argv/ps
        with open(os.open(init, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(f"ATTACH '{path}' AS {alias} (ENCRYPTION_KEY '{read_key(keyfile)}', READ_ONLY);\nUSE {alias};\n")
        os.execvp("duckdb", ["duckdb", "-init", init])
        return
    vendors = [a.vendor] if a.vendor else list(VENDORS)
    if a.step == "check":
        return check(vendors)
    steps = ["sync", "load", "deid"] if a.step == "all" else [a.step]
    for step in steps:
        targets = [(v, getattr(VENDORS[v], step)) for v in vendors] if step != "deid" else [("all", deid.run)]
        for name, fn in targets:
            t0 = time.time()
            print(f"== {step} {name}", file=sys.stderr)
            fn()
            print(f"== {step} {name} done in {time.time() - t0:.0f}s", file=sys.stderr)
