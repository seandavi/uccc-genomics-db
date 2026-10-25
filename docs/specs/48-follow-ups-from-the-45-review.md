# Spec #48: follow-ups from the #45 review

Issue #48 has one finding from the #45 review, **security-r0-1**. `deid.run()` deletes
`$DATA/genomics.duckdb`, rebuilds it in place and only then runs the leak assert. When the
assert fails, the file that holds the flagged value is already sitting at the path the MCP
server, the cohort API and the dashboard loader read. Since #45 the assert is a
case-insensitive substring match, so this path is more likely to be taken than before.

The fix: build into a temp path next to the real file, and rename it onto `genomics.duckdb`
only after the leak check passes. A failed rebuild leaves the previous good file untouched.

## Goal

1. `genomics deid` writes the new de-identified database to `$DATA/genomics.duckdb.tmp` and
   moves it onto `$DATA/genomics.duckdb` with `os.replace` only after `find_leaks` returns
   nothing.
2. When the build or the leak check fails, `genomics.duckdb` is unchanged (same inode, mtime and
   size), the temp file and its WAL are removed, and the command exits non-zero with the leak
   message, as it does today.
3. The leak check still runs under `python -O`. Today it is a bare `assert`, which `-O` strips,
   and from now on that check is the only thing that gates the rename.
4. A test in `tests/test_pipeline.py` pins 1–3 and checks that `research_id` stays the same
   across rebuilds.

## Non-goals

- No change to `ID_PATTERN`, `find_leaks`, the `DROP` / `HASH` sets, `KEY_COL`, `IDENTITY`,
  id hashing, date shifting, age capping, `sql/*.sql` or the vendor loaders. Every output
  column is computed exactly as before, so **`research_id` and `report_id` stay stable** for the
  same key and the same patient. The new test checks this.
- No change to `config.py` (`DEID_DB`, `connect()`), the MCP server, the cohort API, the
  dashboard loader or the systemd units. None of them open the temp path. They all open
  `DEID_DB`, and they open it per request or per build (`server.get_db()`,
  `summary.json.py`), so after the rename they see the new file without a restart. That is what
  `dashboard/COHORT_TOOL.md` already describes ("The daily `genomics deid` replaces the file").
- No new output path, so no new small-cell rule. Nothing leaves the de-id file in a new way.
  This change narrows what can reach the existing consumers.
- No `fsync` of the directory after the rename. If the host loses power right after the
  rename, the result is either the old file or the new one, never a mix, and the next daily
  rebuild writes it again.
- No new dependencies. Only the stdlib `os` module, which `deid.py` already imports.

## Design

### `src/uccc_genomics/deid.py`

Split the current `run()` in two. **`build(path)`** holds today's body, unchanged apart from
the database path, the `with` block and the explicit raise. **`run()`** owns the temp file and
the rename.

```python
def build(path):
    """Write the de-identified database to `path` (which must not exist); raise AssertionError if
    find_leaks reports any identifier-like token. The connection is closed on return or raise."""
    with connect(deid=(path, DEID_DB_KEY), phi=(PHI_DB, PHI_DB_KEY, "READ_ONLY")) as con:
        con.execute("SET VARIABLE k = ?", [read_key(KEY_FILE)])
        ...  # everything from `present = ...` through the mart prints, unchanged
        # ponytail: leak check — no vendor accession / sample id may survive in any text column
        leaks = find_leaks(con, [*present, "mart"])
        if leaks:  # not `assert`: python -O would strip it, and this check is what gates the rename
            raise AssertionError("identifier-like tokens survived de-identification: " + "; ".join(leaks))


def run():
    tmp = f"{DEID_DB}.tmp"  # built here, renamed onto DEID_DB only after the leak check passes
    stale = (tmp, f"{tmp}.wal")
    for f in stale:  # left by an interrupted run; a leftover WAL could be replayed into the new file
        if os.path.exists(f):
            os.remove(f)
    try:
        build(tmp)
    except BaseException:
        for f in stale:
            if os.path.exists(f):
                os.remove(f)
        raise
    os.replace(tmp, DEID_DB)
    print("wrote", DEID_DB)
```

Details the implementer must keep:

- **The `with` block.** `connect()` returns a `duckdb.DuckDBPyConnection`. Its context manager
  closes the connection on normal exit and on an exception. I checked this in duckdb 1.5.5:
  after an `AssertionError` raised inside the block, `con.execute` raises
  `ConnectionException: Connection already closed!`. Closing checkpoints the WAL into the main
  file and deletes `<path>.wal`. The connection has to be closed before `run()` removes or
  renames the file. An open connection that gets garbage-collected later could write a WAL next
  to a path that is already gone.
- **`build()` keeps everything else exactly as it is today.** It still builds the `xw` temp
  table, does the per-table copy, runs `{s}_views.sql`, loads `reference.disease_crosswalk`,
  runs `unified.sql` and `mart.sql`, and prints the same row counts. The body moves under the
  `with` and is re-indented by one level. Nothing else changes. The `os.remove(DEID_DB)` at the
  top of today's `run()` goes away: the real file is never deleted, only replaced.
- **Catalog alias.** The file is still attached as `deid`, so `USE deid`,
  `current_database()` in `find_leaks` and the views stored in the file resolve exactly as
  before. Nothing in the database depends on the file name. I checked this: a file built as
  `x.duckdb.tmp` with a view in it, renamed to `x.duckdb` and attached read-only under a
  different alias, answers queries through that view.
- **Encryption** is per key, not per path. The temp file uses `DEID_DB_KEY` and is the same
  AES-256-GCM file that `connect()` writes today.
- **`os.replace`** is an atomic rename on POSIX. The temp file sits in the same directory as
  `DEID_DB`, so it is on the same filesystem. A process that still has the old file open keeps
  reading the old inode until it closes it. The next open gets the new file. I checked both in
  duckdb 1.5.5 with encrypted files.
- **The cohort API's vocab cache** (`cohort_api.vocab()`) reloads when
  `os.path.getmtime(DEID_DB)` changes. The renamed file keeps the temp file's mtime, which is
  newer, so the reload still fires.
- **The exception type stays `AssertionError` and the message text is unchanged**
  (`identifier-like tokens survived de-identification: schema.table.column: n; ...`). The CLI
  doesn't catch it, so `genomics deid` / `genomics all` exit non-zero with the traceback on
  stderr. In `genomics.service` that fires `OnFailure=ntfy-notify` and skips the dashboard
  build and deploy, as it does today. The difference is that the MCP server and cohort API keep
  serving yesterday's good file instead of the flagged one.
- `except BaseException` (not `Exception`) also cleans up after `KeyboardInterrupt` /
  `SystemExit`. A `SIGKILL` leaves the temp file behind. The next run removes it before it
  builds (the `stale` loop at the top).

Side effect, and a good one: today `genomics.duckdb` is locked by the writer for the whole
deid run. A read-only attach from another process fails during that window, so the MCP server
and cohort API error for the duration of the rebuild. With this change the writer only locks
the temp file, so consumers keep reading the old file until the rename.

Module docstring: replace the last line ("Fails (assert) if ...") with:

```
Built into genomics.duckdb.tmp and renamed onto genomics.duckdb only after the leak check passes:
it fails (AssertionError) if any text column in the vendor or mart schemas still contains an
ID_PATTERN token, in any case, and a failed run leaves the previous genomics.duckdb in place.
```

### `.gitignore`

Add `*.duckdb.tmp.wal` under the DuckDB block, next to `*.duckdb.wal` and `*.duckdb.tmp`. The
temp file lives in `$DATA`, outside the repo, but AGENTS.md promises that `*.duckdb*` is
gitignored. The temp file's WAL (`genomics.duckdb.tmp.wal`) is the only new name that the
current patterns miss.

### `README.md`

In **De-identification (`deid.py`)**, replace the last bullet ("Asserts no Caris/FMI accession
or sample-id pattern survives in any text column of the output.") with:

```
- Asserts no Caris/FMI accession or sample-id pattern survives in any text
  column of the output. The new file is built as `genomics.duckdb.tmp` and
  renamed onto `genomics.duckdb` only when that check passes, so a failed
  rebuild leaves the previous file (and the MCP server / cohort API) as they were.
```

No other design doc changes. ARCHITECTURE.md, COHORT_DISCOVERY.md, COHORT_TOOL.md and PLAN.md
say nothing about how the file is written, and COHORT_TOOL.md's "the daily rebuild replaces the
file" is still true.

### `tests/test_pipeline.py`

One new test. It reuses the existing `pipeline()`, `genomics()`, `FMI` fixture text and
`find_leaks`. It has its own temp `DATA` dir (`tmp_path`) because it rebuilds that dir three
times, and the module-scoped `db` fixture must not see that.

```python
def test_deid_replaces_file_only_after_leak_check(tmp_path):
    data = str(tmp_path)
    con = pipeline(data, {"ORD-0001234-01.xml": FMI})
    ids = con.execute("SELECT vendor, research_id FROM db.unified.report ORDER BY ALL").fetchall()
    con.close()
    path, tmp = f"{data}/genomics.duckdb", f"{data}/genomics.duckdb.tmp"
    first = os.stat(path)

    # A leftover temp file and WAL from an interrupted run are cleared, not attached
    for f in (tmp, f"{tmp}.wal"):
        open(f, "wb").write(b"not a duckdb file")
    genomics(data, "deid")
    good = os.stat(path)
    assert good.st_ino != first.st_ino  # renamed into place, not rewritten
    assert not os.path.exists(tmp) and not os.path.exists(f"{tmp}.wal")

    # An id embedded in FMI free text fails the leak check: the previous file stays
    open(f"{data}/raw/fmi/ORD-0001234-01.xml", "w").write(
        FMI.replace("TP53 R175H was reviewed.", "TP53 R175H ORD-0001234-01 was reviewed."))
    genomics(data, "load", "--vendor", "fmi")
    with pytest.raises(subprocess.CalledProcessError) as e:
        genomics(data, "deid")
    assert "identifier-like tokens survived de-identification" in e.value.stderr
    after = os.stat(path)
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (good.st_ino, good.st_mtime_ns, good.st_size)
    assert not os.path.exists(tmp) and not os.path.exists(f"{tmp}.wal")

    from uccc_genomics.deid import find_leaks
    con = duckdb.connect()
    con.execute(f"ATTACH '{path}' AS db (ENCRYPTION_KEY '{open(f'{data}/.db_key').read().strip()}', READ_ONLY)")
    con.execute("USE db")
    assert find_leaks(con, ["caris", "fmi", "mart"]) == []
    assert con.execute("SELECT vendor, research_id FROM unified.report ORDER BY ALL").fetchall() == ids
```

Why each assertion is there:

- **The junk temp file.** It isn't a DuckDB file, so `ATTACH` fails with "not a valid DuckDB
  database file" (checked in duckdb 1.5.5). The second `deid` succeeds only if `run()` deletes
  the leftovers before it builds.
- **`st_ino` differs after the good rebuild.** That proves the rename. The temp file is created
  while the old file still exists, so the two can't share an inode. Today's `os.remove` and
  re-create gets the freed inode back on this host's XFS `$DATA`, so on `main` the test already
  fails here. I ran it against `main` to check.
- **The leaky FMI interpretation** is the case #45 already showed reaches the assert (the
  `fmi` free-text column survives deid). The `load --vendor fmi` is a full drop-and-rebuild of
  the `fmi` schema in the PHI file, as every load is.
- **Unchanged `(st_ino, st_mtime_ns, st_size)` after the failed run.** That proves the real
  file was never touched. Today's code deletes and rewrites it, so this line would fail on
  `main` too, even on a filesystem that hands out a fresh inode.
- **`find_leaks == []` on the surviving file, and the same `research_id`s as the first build.**
  The file is still the good, readable one, and the extra rebuild through the temp path didn't
  change any id (the AGENTS.md rule for `deid.py` changes).

## Acceptance criteria

- [ ] `deid.run()` never calls `os.remove(DEID_DB)`. It builds into `f"{DEID_DB}.tmp"` and calls
      `os.replace(tmp, DEID_DB)` only after `build()` returns.
- [ ] `deid.build(path)` exists with that signature. It opens its connection in a `with` block
      and raises `AssertionError` with the unchanged message when `find_leaks` returns anything.
      The module has no bare `assert` left on the leak path.
- [ ] Before building, `run()` removes `genomics.duckdb.tmp` and `genomics.duckdb.tmp.wal` if
      they exist. When `build()` raises anything, it removes them again and re-raises.
- [ ] `test_deid_replaces_file_only_after_leak_check` passes. It fails on today's in-place
      rebuild (at the `st_ino` assertion).
- [ ] Every existing test in `tests/test_pipeline.py` passes unchanged. Fixtures `db`,
      `monitor_db` and `wts_db` all go through the new temp-and-rename path.
- [ ] `uv run pytest -q` passes. On the pipeline host the real-DB tests
      (`test_dashboard_loaders.py`, the cohort API real-DB test) behave as before. Nothing here
      touches the real file until the daily timer runs.
- [ ] The `deid.py` docstring, the README De-identification bullet and `.gitignore` are updated
      as in Design.
- [ ] No change to `config.py`, `sql/`, `mcp/`, `dashboard/` or `systemd/`.

## Test plan

- Run `uv run pytest -q` in the worktree. CI runs the same command with no `$DATA`. The new test
  builds synthetic Caris JSON and FMI XML under `tmp_path` and never reads `$DATA/raw/` or the
  PHI file.
- Dashboard check: n/a. This is a Python-only change. `cd dashboard && npm ci && npm test` is
  unaffected but can run as usual.
- Regression checks for the implementer, in a scratch copy and never committed:
  1. Restore `os.remove(DEID_DB)` and build straight into `DEID_DB`. The `st_ino` assertion
     fails. If it is skipped, the unchanged-stat assertion fails.

  While writing this spec I applied the design to a scratch copy of `deid.py` (reverted, not
  committed). The new test passed, and the existing suite (`uv run pytest -q`) reported 65 passed and 3 skipped.
  2. Drop the leftover cleanup at the top of `run()`. The second `deid` fails on the junk temp
     file.
  3. Drop the cleanup in the `except` branch. The "no temp file after failure" assertion fails.
- Don't run `genomics deid` against the real `$DATA`. The daily timer picks this up on its next
  run.

## Risks

- **The disk briefly holds two de-id files.** Until the rename, `$DATA` holds both the old
  `genomics.duckdb` and the new `.tmp`, so the volume needs room for two copies. Today's code
  deletes first, so it never needed that. `$DATA` already holds the larger PHI file and the raw
  mirror, so one more de-id file's worth of headroom is a small ask. If the disk fills, the build
  fails, the temp file is removed and yesterday's file stays.
- **A run killed with `SIGKILL` or by OOM leaves `genomics.duckdb.tmp`** (de-identified,
  encrypted with `.db_key`, never read by a consumer) until the next run removes it. It holds no
  more than `genomics.duckdb` already does, except when the kill lands between a failed leak
  check and the cleanup. That window is a few file deletions long.
- **Stale `genomics.duckdb.wal`.** If one were ever left next to the real file, it would sit
  next to a renamed-in file it doesn't belong to. Today that can only happen if a writer crashed
  with `genomics.duckdb` open, and the only writer was `deid.run()`. After this change nothing
  ever opens `genomics.duckdb` for writing, so no such WAL can be created. README's Cleanup
  section already covers removing `$DATA/*.duckdb.wal`.
- **`build()` is a seam.** It is the same code as today's `run()` body, re-indented. A careless
  re-indent could drop a step (for example the `{s}_views.sql` execute in the vendor loop). The
  existing pipeline tests cover every step: vendor tables, views, crosswalk, `unified.*`,
  `mart.*` and the leak check. Reviewers should still read the diff with whitespace ignored
  (`git diff -w`).
