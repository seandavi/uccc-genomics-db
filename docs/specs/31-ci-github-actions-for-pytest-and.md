# Spec #31: CI on GitHub Actions; plain `uv sync` installs `mcp/`

Part of #23. Closes #29.

## Goal

1. Every pull request and every push to `main` runs the Python tests and the dashboard tests on a
   GitHub-hosted runner, so "merge when CI is green" (AGENTS.md, Git) means something.
2. A fresh clone passes `uv sync && uv run pytest` with no `.env`, no credentials and no sibling
   checkouts. Today collection of `tests/test_cohort_api.py` fails with
   `ModuleNotFoundError: jwt` / `uccc_genomics_mcp`, because a plain `uv sync` installs only the
   root package and the `mcp/` workspace member is left out.
3. AGENTS.md, README.md and `.pi/crucible.json` give the same test commands: the plain forms.

## Non-goals

- No change to any code under `src/uccc_genomics/`, `mcp/src/`, `dashboard/src/`, `systemd/` or
  `tests/`. No data, schema, de-identification or output-path change: nothing new leaves the de-id
  file, and `research_id` / `report_id` are untouched.
- No ruff step in CI (ruff is advisory; existing findings would fail it).
- No `npm run build` in CI: the loader needs the real de-id file, which the runner doesn't have.
- No deploy job, no secrets, no `pull_request_target`, no matrix (one Python, one Node).
- Not making `mcp/pyproject.toml` declare `pyjwt`/`cryptography` directly. They arrive today
  through `mcp`'s own dependencies; whether to make that explicit is a separate question.

## Design

### 1. Root environment installs the `mcp/` member (#29)

`pyproject.toml` (root) gets one more dev dependency and a workspace source for it:

```toml
[dependency-groups]
dev = ["pytest>=8", "uccc-genomics-mcp"]

[tool.uv.workspace]
members = ["mcp"]

[tool.uv.sources]
uccc-genomics-mcp = { workspace = true }
```

`uv.lock` is regenerated with `uv lock` (or as a side effect of `uv sync`). The expected lock diff
is small: under the `uccc-genomics-db` package, `[package.dev-dependencies] dev` gains
`{ name = "uccc-genomics-mcp" }` and `[package.metadata.requires-dev] dev` gains
`{ name = "uccc-genomics-mcp", editable = "mcp" }`. No other package versions move.

Why this works: uv installs the `dev` group by default on `uv sync` / `uv run`, and a workspace
source installs the member editable, so `jwt`, `cryptography`, `starlette` (pulled in by `mcp`)
and `uccc_genomics_mcp` land in the root `.venv`. The cycle (`uccc-genomics-mcp` depends on
`uccc-genomics-db`, whose dev group depends on `uccc-genomics-mcp`) is fine for uv. Checked with
uv 0.11.21 on a clean clone with `DATA` pointed at an empty dir: `uv sync` then `uv run pytest -q`
gave 45 passed, 3 skipped (the real-DB tests); `uv sync --locked` and
`uv sync --all-packages --locked` both accept the regenerated lock.

Side effect on the host: the systemd units run `uv run genomics-mcp` / `uv run genomics-cohort-api`
from the repo root. They already work because the venv was synced with `--all-packages`; after
this change a plain `uv run` also installs the member, so they keep working. The units don't
change.

### 2. Workflow: `.github/workflows/ci.yml` (new)

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.3.2
      - run: uv sync --locked
      - run: uv run pytest -q

  dashboard:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: dashboard
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: dashboard/package-lock.json
      - run: npm ci
      - run: npm test
```

Details the implementer must keep:

- **Triggers:** `pull_request` (default types) and `push` to `main` only. Never
  `pull_request_target`. No `secrets.*` and no `env:` with credentials anywhere in the file.
- **Permissions:** top-level `contents: read`; nothing else is needed.
- **Python:** `setup-uv` installs uv; `uv sync` then provisions Python 3.12 from `.python-version`.
  No `actions/setup-python`. `--locked` fails the job if `uv.lock` is stale against
  `pyproject.toml`, so a forgotten `uv lock` shows up in CI rather than on the host. `setup-uv`'s
  default `enable-cache: auto` caches on GitHub-hosted runners; leave it at the default.
- **Real-DB tests skip:** `DATA` is unset on the runner, so `config.DEID_DB` is
  `/data/davsean/genomics/genomics.duckdb`, which doesn't exist there.
  `tests/test_dashboard_loaders.py` and the real-DB test in `tests/test_cohort_api.py` skip on
  their existing `skipif(not os.path.exists(DEID_DB))`. Do not set `DATA` in the workflow.
- **Node:** 22 (Observable Framework's lock pulls packages that need `node >= 22`; the pipeline
  host runs 22). `npm test` is `node --test` over `dashboard/test/`.
- **Action pins.** The issue asks for major tags. `actions/checkout` and `actions/setup-node`
  publish floating majors (`v7`, verified via `gh api repos/<repo>/git/ref/tags/v7`).
  `astral-sh/setup-uv` stopped publishing floating major tags after `v7.x` (its tag list has
  `v10.3.2`, `v10.0.0`, `v9.0.0`, ... but no `v10` or `v9`), so it is pinned to its latest full
  release tag, `v10.3.2`. Use `@v10.3.2`, not `@v10`, which doesn't resolve. This deviates from the
  wording of the issue only because the major tag doesn't exist.

### 3. One set of test commands across AGENTS.md, README.md, `.pi/crucible.json`

Pick the plain forms everywhere.

- **AGENTS.md, Commands block:** replace the two `--all-packages` lines with
  ```bash
  uv sync                             # root + mcp/ workspace member (via the root dev group)
  uv run pytest -q                    # ~10-30 s; real-DB tests skip when $DATA/genomics.duckdb is absent
  ```
  and delete the paragraph sentence "Plain `uv sync && uv run pytest` fails on a fresh checkout
  (missing `jwt`/`uccc_genomics_mcp`; issue #29); use the `--all-packages` forms." Keep the
  following sentence about `npm run build` needing the real de-id file. Add one sentence after it:
  "CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, `uv run pytest -q` and the dashboard
  `npm ci && npm test` on every PR and push to `main`; it has no `$DATA`, so real-DB tests skip
  there."
- **AGENTS.md, pi-crucible, "Checks a run should use":** `uv run pytest -q` (was
  `uv run --all-packages pytest -q`).
- **README.md:** already says `uv sync` and `uv run pytest`; no change.
- **`.pi/crucible.json`:**
  - `checks[0].command`: `"uv sync && uv run pytest -q"`.
  - `implement`: replace "Run `uv sync --all-packages` first in a fresh worktree (plain `uv sync`
    misses the mcp/ member)." with "Run `uv sync` first in a fresh worktree." Rest of the string
    unchanged.
  - `/crucible` reads this file from `origin/main`, so the new check takes effect after merge.
    The old `--all-packages` command keeps working after the change, so runs in flight are fine.

No other doc mentions `--all-packages` (checked with grep over `*.md`, `*.json`, `*.toml`,
`*.service`).

### Privacy

No new output path. The workflow runs only synthetic tests (temp `DATA` dirs built by
`tests/test_pipeline.py` and the in-test DuckDB fixtures); the runner has no `$DATA`, no keys, no
`.env`. Test logs printed by CI are public: tests must keep printing nothing derived from real data,
which holds because no real data exists on the runner.

## Acceptance criteria

- [ ] `.github/workflows/ci.yml` exists with the triggers, permissions, jobs and steps above; no
      `pull_request_target`, no `secrets.` reference, no `DATA` env.
- [ ] Actions are pinned as `actions/checkout@v7`, `actions/setup-node@v7`,
      `astral-sh/setup-uv@v10.3.2`.
- [ ] Root `pyproject.toml` dev group contains `uccc-genomics-mcp` with
      `[tool.uv.sources] uccc-genomics-mcp = { workspace = true }`; `uv.lock` is regenerated and
      `uv sync --locked` passes.
- [ ] From a fresh `git clone` of the branch into a temp dir, with `DATA` pointed at an empty temp
      dir and no `.env`: `uv sync && uv run pytest -q` passes (real-DB tests skip), and
      `cd dashboard && npm ci && npm test` passes.
- [ ] `uv run --all-packages pytest -q` in the worktree still passes (on the pipeline host the
      real-DB tests run read-only against the real de-id file).
- [ ] AGENTS.md (Commands block, the #29 caveat removed, CI sentence added, crucible checks line)
      and `.pi/crucible.json` (`checks[0].command`, `implement`) use the plain forms; no
      `--all-packages` remains in AGENTS.md, README.md or `.pi/crucible.json`.
- [ ] `.pi/crucible.json` is still valid JSON (`python3 -m json.tool .pi/crucible.json`).
- [ ] The CI workflow runs green on the PR for this issue (both jobs).

## Test plan

No new pytest or node tests: this change adds no logic, and the workflow itself is the check.

1. `uv lock && uv sync --locked && uv run pytest -q` in the worktree.
2. Fresh-clone check (the #29 reproduction), in a temp dir under `$TMPDIR`, never `/tmp` on this
   host:
   ```bash
   T=$(mktemp -d); git clone -q <worktree> "$T/repo"; cd "$T/repo"
   DATA="$T/nodata" uv sync && DATA="$T/nodata" uv run pytest -q   # expect: passed, 3 skipped
   (cd dashboard && npm ci && npm test)
   ```
   `DATA` points at an empty dir so the host's real de-id file isn't used, matching the runner.
3. Workflow syntax: push the branch; the PR's checks must show `CI / pytest` and
   `CI / dashboard` green. (No local runner like `act`; don't add one.)
4. `grep -rn -- --all-packages AGENTS.md README.md .pi/crucible.json` prints nothing.

## Risks

- **`setup-uv` tag drift.** A full-version pin won't pick up fixes automatically. Acceptable;
  bump by hand (or Dependabot later; not in scope).
- **`--locked` strictness.** A PR that edits `pyproject.toml` without `uv lock` fails CI. That's
  intended.
- **Upstream resolution changes.** `uv sync --locked` installs exactly the lock, so CI matches the
  host; no surprise upgrades.
- **Host venv.** After merge, the next `uv run` on the host (daily timer, services) installs the
  dev group, including `pytest` and the editable `mcp/` member, into the shared `.venv`. The
  member is already there from earlier `--all-packages` syncs, so nothing changes in practice.
- **Public logs.** CI output is public. The runner has no real data, so nothing real can be
  printed; a future test that reads `$DATA` must keep its `skipif`.
