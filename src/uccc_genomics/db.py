"""Bulk insert Python rows into a DuckDB table via a temp JSONL file.

executemany() is row-by-row in DuckDB's Python API (~2 ms/row => minutes for
100k rows). Writing JSONL and reading it back with try_cast per column is a
few seconds for the same data and tolerates vendor date formats.
"""
import json
import os
import tempfile


def bulk_insert(con, table, rows):
    if not rows:
        return
    cols = [(r[0], r[1]) for r in con.execute(f"DESCRIBE {table}").fetchall()]
    assert len(cols) == len(rows[0]), f"{table}: {len(cols)} columns vs {len(rows[0])} values per row"
    names = [c for c, _ in cols]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    try:
        with os.fdopen(fd, "w") as f:
            for r in rows:
                f.write(json.dumps(dict(zip(names, r)), default=str) + "\n")
        struct = ", ".join(f"'{c}': 'VARCHAR'" for c in names)
        sel = ", ".join(f'try_cast("{c}" AS {t}) AS "{c}"' for c, t in cols)
        con.execute(f"INSERT INTO {table} SELECT {sel} FROM read_json('{path}', format='newline_delimited', columns={{{struct}}})")
    finally:
        os.remove(path)
