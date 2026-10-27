# Spec #75: FMI sync fails silently; add a staleness check

`fmi.sync()` runs `ssh host 'cd dir && tar cf - *.xml' | tar xf - -C $DATA/raw/fmi` through
`subprocess.run(..., shell=True, check=True)`. A shell pipeline returns the status of its last
command. When the source directory is empty or unmounted, the remote `tar` prints
`*.xml: Cannot stat`, still writes an empty archive (end-of-archive blocks) and exits 2. The local
`tar xf` reads that empty archive, exits 0, and the pipeline reports success. The daily job then
reloads the old mirror and no ntfy alert fires. (Checked locally: an empty source gives
pipeline status 0. Feeding the local `tar` a truly empty stdin exits 2, so the empty archive is
what hides the failure.)

## Goal

1. `genomics sync --vendor fmi` exits non-zero when ssh or the remote side fails, including a
   remote `tar` that fails after it has written part of the stream.
2. It exits non-zero, with a clear message, when the source directory holds no `*.xml` files
   or can't be entered (unmounted share, missing path).
3. A new step `genomics check [--vendor caris|fmi]` exits non-zero when a vendor's newest
   received date in the PHI file is older than `STALE_DAYS` days (default 21). The daily unit
   runs it last, so ntfy fires when a source has quietly stopped delivering. This covers both
   vendors and any cause, including ones that sync can't see.
4. Tests with a fake `ssh` and source directory: remote failure, empty source, missing source,
   success, and stale/fresh data.

## Non-goals

- No change to `deid.py`, the PHI column lists, id hashing, date shifting or the leak assert.
  `research_id` and `report_id` are unaffected: no load or de-id code changes.
- No schema change: no table or column is added, dropped or renamed in either DuckDB.
- No change to `caris.sync()`. `aws s3 sync ... check=True` already fails on access or network
  errors. A bucket that simply stops receiving deliveries is caught by `genomics check`.
- No new output path from the de-id file. `check` prints only per-vendor ages in days and the
  limit, never dates, ids or counts. It reads the PHI file read-only and its output goes to the
  host journal, the same place sync/load output goes today.
- `check` is not added to `genomics all`. If `all` exited non-zero on stale data, systemd would
  skip the dashboard build and deploy, holding back the fresh vendor's data along with the
  stale one's. The issue asks for a warning, not a blocked rebuild (see Design §3).
- No retry or partial-sync recovery. A failed sync stops the run. The next daily run copies
  everything again.
- No change to the FMI host mount (ops, done by hand per the issue comment).
- No new dependencies (stdlib `subprocess`, `shlex`, `datetime`).

## Design

### 1. `src/uccc_genomics/fmi.py`: `sync()`

Replace the `shell=True` pipeline with two processes connected by a pipe, and check both exit
statuses. This is the "replacing a shell pipeline" pattern from the `subprocess` docs. Add
`import shlex`. The signature stays `def sync() -> None`.

```python
def sync():
    # ponytail: full tar copy every run (rsync isn't on the FMI host); ~450 MB, fine daily
    host, path = FMI_SRC.split(":", 1)
    os.makedirs(RAW_FMI, exist_ok=True)
    # Both exit statuses are checked: in a shell pipeline only the local tar's counted, so an
    # empty or unmounted source looked like success (#75).
    remote = (f'cd {shlex.quote(path)} || exit 1; set -- *.xml; '
              '[ -e "$1" ] || { echo "no *.xml in $PWD" >&2; exit 1; }; exec tar cf - -- "$@"')
    ssh = subprocess.Popen(["ssh", "-o", "BatchMode=yes", host, remote], stdout=subprocess.PIPE)
    untar = subprocess.Popen(["tar", "xf", "-", "-C", RAW_FMI], stdin=ssh.stdout)
    ssh.stdout.close()  # so ssh gets SIGPIPE if the local tar dies first
    untar_rc, ssh_rc = untar.wait(), ssh.wait()
    if ssh_rc or untar_rc:
        sys.exit(f"fmi sync failed: ssh/remote exit {ssh_rc}, local tar exit {untar_rc}")
```

- The remote command is POSIX `sh`, so it works whatever the login shell on the FMI host is and
  under `/bin/sh` (dash) in CI. `set -- *.xml` leaves the literal `*.xml` in `$1` when nothing
  matches, so `[ -e "$1" ]` is the zero-files guard. It runs before `tar`, so nothing reaches
  the local mirror.
- The message uses the remote `$PWD` (the directory after `cd`), so the path never has to be
  quoted twice. Tests match only the prefix `no *.xml in `.
- `sys.exit(str)` matches how `load()` reports a missing mirror (exit status 1, message on
  stderr). systemd's `OnFailure=ntfy-notify@%N.service` then fires.
- The local mirror is not cleared first. On a failure part-way through the stream, one file
  may be left truncated. The run stops before load, and the next successful sync overwrites
  it (see Risks).

### 2. `src/uccc_genomics/config.py`: `STALE_DAYS`

```python
STALE_DAYS = int(os.environ.get("STALE_DAYS") or 21)  # genomics check: max age (days) of a vendor's newest received date
```

`or 21` makes an empty value (`STALE_DAYS=`) mean the default. The test uses that to pin the
default even when a repo-root `.env` sets the variable. A non-integer value raises `ValueError`
at import, so the run fails loudly.

`.env.example` gets a commented line after `FMI_SRC`:

```
# STALE_DAYS=21   # genomics check fails when a vendor's newest received date is older than this
```

### 3. `src/uccc_genomics/cli.py`: `check` step

Add `"check"` to the `step` choices and a module-level query map and function:

```python
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
```

- Vendor source fields (PLAN.md mapping; the same columns `unified.report.received_on` is built
  from in `sql/unified.sql`): Caris `caris.report.received_at` (JSON
  `testDetails.receivedDate`), FMI `fmi.report.received_on` (XML `Sample/ReceivedDate`, else
  `PMI/ReceivedDate`).
- It reads the PHI file because the de-id copies of these dates are shifted per patient, so
  their maximum isn't the real newest date. Only the integer age is printed.
- `age is None` means no non-null received date at all, and counts as stale. A missing
  `caris.report`/`fmi.report` table (vendor never loaded) raises `duckdb.CatalogException`.
  That also exits non-zero, which is the right outcome, so there's no special handling.
- Boundary: `age == STALE_DAYS` passes and `age > STALE_DAYS` is stale.
- Every requested vendor is checked before exiting, so one alert names all stale vendors.
- `main()` dispatches it before the step loop, like `shell`:
  `if a.step == "check": return check([a.vendor] if a.vendor else list(VENDORS))`.
  `--vendor` limits the check. The default checks every vendor.
- Imports added to `cli.py`: `from datetime import date`, and `connect`, `STALE_DAYS` from
  `.config` (`PHI_DB` and `PHI_DB_KEY` are already imported).
- Module docstring: add the line `genomics check [--vendor caris|fmi]   # exit non-zero if a
  vendor's newest received date is older than STALE_DAYS (default 21)`.

### 4. `systemd/genomics.service`

Append, after the deploy `ExecStart`:

```
# Last, so the day's rebuild and deploy still go out; non-zero (stale vendor data) fires ntfy (#75).
ExecStart=%h/.local/bin/uv run genomics check
```

A failing sync still stops the unit at the first `ExecStart`, as any failure does today. The
unit file is symlinked into `~/.config/systemd/user`. A person runs
`systemctl --user daemon-reload` after merge; agents don't (AGENTS.md).

### 5. Docs

- `README.md`: in the Run block add `uv run genomics check            # fail if a vendor's newest
  received date is older than STALE_DAYS (21)`. In the "Scheduled daily" paragraph, add one
  sentence: the unit runs `genomics check` last, so ntfy fires when either vendor's newest
  received date is older than `STALE_DAYS`, and the FMI sync fails (rather than reusing the old
  mirror) when the share is empty or unmounted. Update the Layout `cli.py` line to
  `genomics sync|load|deid|all|check [--vendor] | shell [--phi]`. Mention `STALE_DAYS` next to
  `CARIS_BUCKET`/`FMI_SRC` in the `.env` paragraph.
- `AGENTS.md`: update the Layout `cli.py` line the same way.

## Acceptance criteria

- [ ] `fmi.sync()` makes no `shell=True` call. It runs `ssh` and a local `tar xf - -C RAW_FMI`
      as two `Popen`s and exits non-zero if either exits non-zero.
- [ ] With the fake ssh and a source holding only an empty directory, `genomics sync --vendor
      fmi` exits non-zero, stderr contains `no *.xml in `, and a file already in
      `$DATA/raw/fmi/` is byte-for-byte unchanged.
- [ ] With a source path that doesn't exist, it exits non-zero.
- [ ] With a valid source but the fake ssh forced to exit 2 after streaming the archive, it
      exits non-zero. This is the case the old pipeline hid.
- [ ] With a valid source of two synthetic XMLs, it exits 0 and both files appear in
      `$DATA/raw/fmi/` with identical content.
- [ ] `genomics check` prints one `== check <vendor>: newest received date is <n> days old
      (limit <N>)` line per vendor to stderr, with no dates, ids or counts.
- [ ] `genomics check` exits non-zero, naming exactly the vendors older than `STALE_DAYS`, and
      exits 0 when none are. `age == STALE_DAYS` passes.
- [ ] `STALE_DAYS=` (empty) yields limit 21.
- [ ] `--vendor fmi` checks only FMI.
- [ ] `systemd/genomics.service` runs `genomics check` as its last `ExecStart`. `README.md`,
      `AGENTS.md`, `.env.example` and the `cli.py` docstring are updated as in Design §5.
- [ ] `uv run pytest -q` passes. Dashboard and web checks are n/a (no change under
      `dashboard/` or `web/`, and no API model change).

## Test plan

All in `tests/test_pipeline.py`. Nothing reads `$DATA/raw/` or the PHI file. Every subprocess
gets `DATA` set to a pytest temp dir and an explicit `FMI_SRC`, so the real FMI host and real
`$DATA` are never touched. (`.env` values are `setdefault`, so the test environment wins.)

**Fake ssh.** A helper `fake_ssh(tmp_path) -> str` writes `tmp_path/bin/ssh` (mode 0o755) and
returns the `bin` directory:

```sh
#!/bin/sh
# fake ssh: drop -o options and the host, run the remote command locally
while [ "$1" = "-o" ]; do shift 2; done
shift
sh -c "$1"; rc=$?
exit "${FAKE_SSH_EXIT:-$rc}"
```

A helper `fmi_sync(data, src, bin_dir, **env) -> subprocess.CompletedProcess` runs
`uv run genomics sync --vendor fmi` with `cwd=ROOT`, `capture_output=True`, `text=True`, no
`check`, and env `{**os.environ, "DATA": data, "FMI_SRC": f"fakehost:{src}",
"PATH": f"{bin_dir}:{os.environ['PATH']}", **env}`.

Tests (synthetic content only: the existing `FMI` string, or `"<x/>"`, since sync doesn't
parse):

1. `test_fmi_sync_copies_xml`: src with `A.xml` and `B.xml` → returncode 0, both in
   `DATA/raw/fmi` with the same content.
2. `test_fmi_sync_fails_on_empty_source`: empty src dir, and `DATA/raw/fmi/old.xml`
   pre-written → returncode != 0, `"no *.xml in "` in stderr, `old.xml` content unchanged.
3. `test_fmi_sync_fails_on_missing_source`: src path that doesn't exist → returncode != 0.
4. `test_fmi_sync_fails_when_remote_fails`: src with `A.xml`, `FAKE_SSH_EXIT="2"` →
   returncode != 0 (the archive streamed fine, so only the ssh status catches it).

**Staleness.** `test_check_flags_stale_vendor(tmp_path)` builds a PHI file with the existing
`pipeline(str(tmp_path), {"ORD-0001234-01.xml": FMI})` (Caris `receivedDate` 2026-01-07, FMI
`ReceivedDate` 2026-01-10), closes the returned connection, then runs `uv run genomics check`
the same way (no `check=True`, `capture_output=True`, `DATA` set). With
`fmi_age = (date.today() - date(2026, 1, 10)).days` (Caris is `fmi_age + 3`):

- `STALE_DAYS=str(fmi_age)` → returncode != 0, last stderr line is
  `stale vendor data: caris (newest received date older than {fmi_age} days)`, and stderr
  contains `== check fmi: newest received date is {fmi_age} days old`. This pins the boundary
  (FMI at exactly the limit passes) and per-vendor reporting.
- `STALE_DAYS=str(fmi_age + 3)` → returncode 0.
- `STALE_DAYS=str(fmi_age)` with `--vendor fmi` → returncode 0.
- `STALE_DAYS=""` → stderr contains `(limit 21)` and returncode != 0 (the fixed 2026-01 dates
  are more than 21 days old from the test's date onward).
- No stderr line contains `2026-01` (no dates printed).

Commands: `uv run pytest -q`. Dashboard and web checks are n/a. Implementers must not run
`genomics sync|check` against the real `$DATA` or the real `FMI_SRC`.

## Risks

- **Partial mirror after a mid-stream failure.** The local `tar` may leave one truncated XML
  in `$DATA/raw/fmi/`. The run exits before load, so it isn't loaded that day. The next
  successful sync overwrites it. If a later manual `genomics load` ran without a fresh sync, the
  file would land in `fmi.load_error` rather than be dropped silently. Accepted. Staging into a
  temp dir and swapping would double disk use for little gain.
- **Remote shell assumptions.** The remote command assumes a POSIX `sh` on the FMI host, which
  any login shell provides. `exec tar cf - -- "$@"` has the same argument-list limit as today's
  `tar cf - *.xml`.
- **`STALE_DAYS` too low for a vendor's real cadence** gives a daily false alarm. It's one env
  var in `.env`. A per-vendor limit can come later if that cadence turns out to differ.
- **Test day rollover.** `date.today()` is computed in the test and again in the subprocess. A
  run that crosses midnight between the two could be off by one. That's a flake risk only, and
  negligible.
- **Unit change needs a person.** The `ExecStart` for `check` takes effect only after merge to
  the main checkout and `systemctl --user daemon-reload`, which agents don't run. The PR carries
  `needs:human` anyway.
