# Spec #129: production deployment, container + compose behind Traefik

## Goal

Run the campus cohort app (`genomics-app` + the built `web/` site) in production on the pipeline
host as one container behind the host's Traefik, signed in through Authentik, reading the
de-identified DuckDB read-only. Ship the `Dockerfile`, `deploy/compose.yaml`, a gitignored
`deploy/.env` with a committed `deploy/.env.example`, a CI job that builds the image (no push) and
validates the compose file, the nightly-rebuild hook that makes the container see the new file, and a
README runbook (build, up, logs, rollback, the GSM secrets it reads, the monode follow-ups for a person).

## Non-goals

- Bringing it up. Agents never run `docker compose up|restart|down` against production; the
  orchestrator does that after merge with Sean's go-ahead.
- Pushing the image to a registry (GHCR or other). It is built and tagged on the host.
- Public `/mcp`. Remote MCP clients (ARCHITECTURE decision 10) remain later work; the tailnet
  `genomics-mcp` service and `genomics-cohort-api` are unchanged.
- monode changes (DNS record, uptime check, GSM secret creation). The README lists them for a person.
- Retiring the Cloudflare dashboard or `genomics-cohort-api` (decision 12's follow-up).
- Any change to the cohort module, suppression, `deid.py`, the mart or the data.

## Findings that shape the design (checked on the host while writing this spec)

1. **A file bind mount does not see a rename.** `deid.py` builds `genomics.duckdb.tmp` and
   `os.replace`s it onto `genomics.duckdb`. A container with the file bind-mounted keeps reading the
   old inode until it restarts; `docker restart` re-resolves the path and sees the new file
   (checked with a throwaway container and a rename). Mounting `$DATA` as a directory is not an
   option: it holds `genomics_phi.duckdb`, `.db_key_phi`, `.deid_key` and `raw/`. So: mount the two
   files read-only, and restart the container from the nightly unit after `genomics all`.
   `cohort.queries.vocabulary()` and `data_date()` key on the file's mtime, which also refreshes
   only after the restart.
2. **`$DATA/.db_key` is mode 600, owned by the host user.** The container must run as that uid:gid
   (`user:` in compose, from `deploy/.env`); the image's own non-root user is the default when run
   elsewhere. Docker here runs without SELinux labelling, so no `:z`.
3. **The hostname does not resolve yet.** The `<APP_HOST>` named in the issue returned NXDOMAIN from
   the host's resolver (Cloudflare SOA in the authority section), and there is no `*.uccc` record in
   monode's `terraform/apps/dns/cancerdatasci_org.tf` (only `insights.uccc`). DoH is blocked from this
   network, so this could not be cross-checked from outside. A grey-cloud A record is a monode
   follow-up and must exist before bring-up: TLS-ALPN-01 can't issue a certificate without it.
4. **Authentik already lists `https://<APP_HOST>/auth/callback`** as a Strict redirect URI on the
   `uccc-genomics` provider (monode `terraform/apps/authentik_config/apps.tf`).
5. **GSM (project per README placeholder `<gsm-project>`)** holds `uccc-genomics-authentik-client-secret`
   and `uccc-genomics-db-password-onclappc02`. There is no session-secret entry for this app yet;
   the runbook creates `uccc-genomics-session-secret` once.
6. The Postgres container on `pg_main_stack_default` is `pg_main`, so `DATABASE_URL` uses host
   `pg_main`. The `uccc_genomics` database is already in monode's backup list.
7. `python:3.12-slim-trixie` has tzdata (`/usr/share/zoneinfo/America/Denver`) and no curl/wget,
   so the healthcheck uses Python. `ghcr.io/astral-sh/uv:0.11.21-python3.12-trixie-slim` exists
   (host uv is 0.11.21; there is no bookworm variant at that version). `oven/bun:1.4.2` exists
   (CI's bun version).
8. Docker's default log driver here is `json-file` with no rotation configured.

## Design

### Hostname stays out of committed files

AGENTS.md: real hostnames beyond the public dashboard domain go in `.env`, not code or docs. The
issue names the host; the committed files use `${APP_HOST}` / `<APP_HOST>` and the value lives only
in `deploy/.env`. `APP_BASE_URL` is derived as `https://${APP_HOST}` in compose, so it is always
https and the session cookies are always `Secure` (`authen._cookie` already keys on the scheme).

### `Dockerfile` (repo root, new)

Three stages; nothing from the build context but the files listed reaches the image.

```dockerfile
# syntax=docker/dockerfile:1
FROM oven/bun:1.4.2 AS web
WORKDIR /web
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
RUN bun run build                        # -> /web/dist (index.html, discover.html, assets/)

FROM ghcr.io/astral-sh/uv:0.11.21-python3.12-trixie-slim AS app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY mcp/pyproject.toml mcp/
COPY src/ src/
COPY mcp/src/ mcp/src/
RUN uv sync --locked --no-dev --no-editable --package uccc-genomics-mcp

FROM python:3.12-slim-trixie
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=app /app/.venv /app/.venv
COPY --from=web /web/dist /app/web/dist
ENV PATH=/app/.venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1 DATA=/data
WORKDIR /app
USER 10001
EXPOSE 8092
ENTRYPOINT ["genomics-app"]
CMD ["--auth", "authentik", "--host", "0.0.0.0", "--port", "8092", "--static", "/app/web/dist"]
```

- `--no-editable` installs both workspace packages into site-packages, so `uccc_genomics.config`'s
  repo-root `.env` loader points at a path that does not exist in the image (no `.env` can be
  picked up, and none is in the context anyway).
- `DATA=/data` makes `uccc_genomics_mcp.server.DEID_DB` = `/data/genomics.duckdb` and
  `DEID_DB_KEY` = `/data/.db_key` (existing env handling; no code change).
- No `HEALTHCHECK` here: the healthcheck lives in compose, following the host's convention.
- `ENTRYPOINT` + `CMD` so a smoke run can pass `--auth none` without rebuilding.

### `.dockerignore` (repo root, new)

An allowlist, so `.env`, `deploy/.env`, `*.duckdb*`, key files, `node_modules` and caches can never
enter the build context:

```
*
!pyproject.toml
!uv.lock
!.python-version
!src/
!mcp/pyproject.toml
!mcp/src/
!web/
web/node_modules/
web/dist/
**/__pycache__/
```

### `deploy/compose.yaml` (new)

```yaml
# genomics-app, the campus cohort site (README "Production (container)", #129).
# Networks: proxy (Traefik, monode compose/traefik) and pg_main_stack_default (Postgres as pg_main).
# Values come from deploy/.env (gitignored; deploy/.env.example lists them). The image bakes in no secrets.
name: uccc-genomics
services:
  genomics-app:
    image: uccc-genomics-app:${APP_TAG:?set APP_TAG in deploy/.env}
    pull_policy: never                 # built on this host; never look for it on a registry
    container_name: uccc_genomics_app  # genomics.service restarts it by this name after the nightly rebuild
    restart: unless-stopped
    user: "${APP_UID:?set APP_UID in deploy/.env}:${APP_GID:?set APP_GID in deploy/.env}"   # owner of $DATA/.db_key (mode 600)
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    networks: [proxy, pg_main_stack_default]
    volumes:
      # Only the de-id file and its key, read-only. Never $DATA itself: it holds the PHI file, its key,
      # .deid_key and raw/. A file mount keeps the old inode after deid's rename, hence the nightly restart.
      # Long syntax: a missing source fails the start instead of becoming an empty directory.
      - {type: bind, source: "${HOST_DATA:?set HOST_DATA in deploy/.env}/genomics.duckdb", target: /data/genomics.duckdb, read_only: true}
      - {type: bind, source: "${HOST_DATA:?set HOST_DATA in deploy/.env}/.db_key", target: /data/.db_key, read_only: true}
    environment:
      APP_BASE_URL: https://${APP_HOST:?set APP_HOST in deploy/.env}
      AUTHENTIK_ISSUER: ${AUTHENTIK_ISSUER:?set AUTHENTIK_ISSUER in deploy/.env}
      AUTHENTIK_CLIENT_ID: ${AUTHENTIK_CLIENT_ID:-uccc-genomics}
      AUTHENTIK_CLIENT_SECRET: ${AUTHENTIK_CLIENT_SECRET:?set AUTHENTIK_CLIENT_SECRET in deploy/.env}
      AUTHENTIK_GROUP: ${AUTHENTIK_GROUP:-uccc-genomics-dashboard}
      SESSION_SECRET: ${SESSION_SECRET:?set SESSION_SECRET in deploy/.env}
      DATABASE_URL: ${DATABASE_URL:?set DATABASE_URL in deploy/.env}
      TZ: America/Denver               # data_date() is the local date of the de-id file's mtime
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=proxy"
      # /mcp is not routed: MCP stays on the tailnet (genomics-mcp). Everything else still needs a login.
      - "traefik.http.routers.uccc-genomics.rule=Host(`${APP_HOST}`) && !PathPrefix(`/mcp`)"
      - "traefik.http.routers.uccc-genomics.entrypoints=websecure"
      - "traefik.http.routers.uccc-genomics.tls=true"
      - "traefik.http.routers.uccc-genomics.tls.certresolver=cloudflare"   # grey cloud: LE via TLS-ALPN-01
      - "traefik.http.services.uccc-genomics.loadbalancer.server.port=8092"
    healthcheck:
      test: ["CMD", "python", "-c", "import sys, urllib.request; sys.exit(b'Healthy' not in urllib.request.urlopen('http://127.0.0.1:8092/api/health', timeout=5).read())"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    logging:                           # stdout carries the query audit log (one JSON line per count/pivot)
      driver: json-file
      options: {max-size: 50m, max-file: "10"}

networks:
  proxy: {external: true}
  pg_main_stack_default: {external: true}
```

- No `ports:`: the app is reachable only on the two docker networks, by Traefik and other members.
- No `env_file:`: only the variables listed reach the container, and `docker compose config`
  works in CI with `--env-file deploy/.env.example`.
- `urlopen` raises on the 503 `/api/health` returns when the de-id file won't open, so the check
  fails then too.
- This exact shape (long-syntax binds, backticks and `!` in the label, `${VAR:?}`) was validated with
  `docker compose config` (compose v5.6.0) while writing the spec.

### `deploy/.env.example` (new; `deploy/.env` is already ignored by `.gitignore`'s `.env`)

Placeholders only:

```
# Copy to deploy/.env (umask 077) and fill in; README "Production (container)" fills the secrets from GSM.
APP_TAG=<short git sha of the built image>
APP_HOST=<public hostname>
APP_UID=<uid owning $DATA/.db_key: stat -c %u>
APP_GID=<gid owning $DATA/.db_key: stat -c %g>
HOST_DATA=<the host's $DATA, e.g. /data/<user>/genomics>
AUTHENTIK_ISSUER=https://<authentik-host>/application/o/uccc-genomics/
AUTHENTIK_CLIENT_ID=uccc-genomics
AUTHENTIK_CLIENT_SECRET=<from GSM uccc-genomics-authentik-client-secret>
SESSION_SECRET=<from GSM uccc-genomics-session-secret>
DATABASE_URL=postgresql://<role>:<url-encoded password>@pg_main:5432/<database>
# AUTHENTIK_GROUP=uccc-genomics-dashboard
```

### `systemd/genomics.service` (change)

Right after `ExecStart=%h/.local/bin/uv run genomics all`, add:

```ini
# The campus app container (deploy/compose.yaml) bind-mounts genomics.duckdb as a file and keeps the
# replaced inode until it restarts (#129). Skipped while the container does not exist.
ExecStart=/bin/sh -c 'if docker container inspect uccc_genomics_app >/dev/null 2>&1; then docker restart uccc_genomics_app; fi'
```

- Placed before the dashboard build so the app gets the new file even if the dashboard deploy fails.
  A failed `genomics all` stops the unit first, so the app keeps serving yesterday's (consistent)
  file. A failed restart fails the unit and fires the existing `OnFailure` ntfy.
- The guard matters: `docker compose restart` / `docker restart` exit 1 when the container does not
  exist (checked), and the unit runs from the main checkout before anyone brings the stack up.
- `docker` is `/usr/bin/docker`, already on the unit's `PATH`. Downtime is the restart (seconds).

### `mcp/src/uccc_genomics_mcp/app.py` (one-line change)

`--static` help text drops "local dev only" (production serves `/app/web/dist` with it):
`help="also serve this built front-end directory (landing page at /, Discover at /discover)"`.
No behaviour change.

### `.github/workflows/ci.yml` (new job)

```yaml
  container:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: docker build -t uccc-genomics-app:ci .
      - run: docker compose -f deploy/compose.yaml --env-file deploy/.env.example config -q
```

No login, no push, no secrets.

### `tests/test_deploy.py` (new)

Pins the properties that keep PHI and `/mcp` off the public route. Reads `docker compose -f
deploy/compose.yaml --env-file deploy/.env.example config --format json` via `subprocess.run(...,
check=True, capture_output=True, text=True)`; the compose tests carry
`pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker compose")`. Tests (names as given):

- `test_compose_mounts_only_the_deid_file_and_its_key_read_only`: the service's `volumes` are exactly
  two, both `type == "bind"` and `read_only is True`, sources ending `/genomics.duckdb` and `/.db_key`,
  targets `/data/genomics.duckdb` and `/data/.db_key`; and the compose file's text contains none of
  `genomics_phi`, `db_key_phi`, `deid_key`, `/raw`.
- `test_compose_routes_no_mcp_and_publishes_no_port`: no `ports` key; the router rule label contains
  ``!PathPrefix(`/mcp`)``; `tls.certresolver` is `cloudflare`.
- `test_compose_uses_https_base_url_and_authentik_env`: `environment["APP_BASE_URL"]` starts with
  `https://`; `SESSION_SECRET`, `AUTHENTIK_CLIENT_SECRET`, `DATABASE_URL` present; no `env_file`.
- `test_dockerignore_is_an_allowlist` (no docker needed, no skip): the first non-comment line of `.dockerignore` is `*`,
  and the set of `!` lines equals exactly `{"!pyproject.toml", "!uv.lock", "!.python-version", "!src/",
  "!mcp/pyproject.toml", "!mcp/src/", "!web/"}`.
- `test_dockerfile_runs_authentik_as_non_root` (no skip): `Dockerfile` text has a `USER 10001` line and its `CMD`
  contains `"--auth", "authentik"`.

The CI pytest job runs on `ubuntu-latest`, which has Docker with the compose plugin, so the compose
tests run there.

### Docs

- **README.md**: under "Cohort app (genomics-app)", replace "Development only: no systemd unit or
  deploy yet." with a pointer to a new `### Production (container)` subsection (after "Discover
  (web/)"), holding:
  - what runs: `Dockerfile` + `deploy/compose.yaml`, routes, `/mcp` not routed, mounts (the two
    files, read-only) and why the nightly unit restarts the container;
  - `deploy/.env` once (umask 077), secrets read from GSM without echoing them:
    `uccc-genomics-authentik-client-secret`, `uccc-genomics-db-password-onclappc02` (URL-encoded
    into `DATABASE_URL` with `python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip(), safe=""))'`),
    `uccc-genomics-session-secret` (created once by a person:
    `python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | gcloud secrets create uccc-genomics-session-secret --data-file=- --project=<gsm-project>`);
    `APP_UID`/`APP_GID` from `stat -c '%u %g' $DATA/.db_key`;
  - migrations: unchanged, `uv run alembic -c mcp/alembic.ini upgrade head` from the host checkout
    when a release adds one (the app never migrates on start);
  - build: `git pull && docker build -t uccc-genomics-app:$(git rev-parse --short HEAD) .`, then set
    `APP_TAG` in `deploy/.env`;
  - validate: `docker compose -f deploy/compose.yaml config -q` (`-q`: plain `config` prints the
    secrets);
  - up: `docker compose -f deploy/compose.yaml up -d`; check `docker compose -f deploy/compose.yaml ps`
    shows `healthy`, then `curl -sS https://<APP_HOST>/api/health` and sign in once (a member gets in,
    `/api/me` answers; `/mcp` gives Traefik's 404);
  - logs: `docker compose -f deploy/compose.yaml logs -f genomics-app` (audit lines are JSON; rotated
    at 10 x 50 MB);
  - rollback: `docker image ls uccc-genomics-app`, set `APP_TAG` to the previous tag, `up -d`;
  - monode follow-ups for a person, before the first `up`: (1) an A record for `<APP_HOST>` to the
    host's public IP, `proxied = false`, in `terraform/apps/dns/cancerdatasci_org.tf`; (2) a second
    uptime check + alert policy in `terraform/apps/uccc_genomics/` on `https://<APP_HOST>/api/health`,
    status 200 and body containing `Healthy`, like the existing one; (3) the GSM session secret above.
    The Authentik redirect URI is already there.
- **docs/ARCHITECTURE.md** "Development": replace "Production hosting (Docker Compose behind
  Traefik) comes after the app works." with "Production runs the same app in a container behind
  Traefik (`Dockerfile`, `deploy/compose.yaml`, #129; README § Production (container)); its public
  router does not route `/mcp`, so remote MCP (decision 10) needs a routing change when it lands."
- **AGENTS.md**: Layout gains `Dockerfile` / `deploy/` (compose.yaml, .env.example; `deploy/.env` is
  gitignored). "Never run the production pipeline or deploys" adds `docker compose -f
  deploy/compose.yaml up|restart|down`, `docker restart uccc_genomics_app` and building/tagging images
  for production. The genomics-app bullet under "Don't weaken Cloudflare Access" adds: in production
  Traefik does not route `/mcp` and the container mounts only `genomics.duckdb` and `.db_key`,
  read-only; keep both.

## Privacy and stability

- **What leaves the host:** the same routes `genomics-app` serves today, now on a public hostname.
  Suppression is unchanged (the cohort module floors and suppresses; `/api/public/summary` is floored
  and rounded); every route but the open ones still needs an Authentik login in the `groups`-claim
  group. `/mcp` is additionally not routed. No new output path, so no new small-cell rule; the tests
  above pin the mounts and the route.
- **PHI:** the container can read only `genomics.duckdb` and `.db_key`, read-only. The PHI file, its
  key, `.deid_key` and `raw/` are never mounted. The build context is an allowlist, so no `.env`,
  database or key enters an image. Secrets live in `deploy/.env` (gitignored) and the container
  environment, never in the image, compose file, CI or logs; the runbook validates with `config -q`.
- **research_id / report_id:** not affected; nothing touches `deid.py`, keys or data.

## Acceptance criteria

- [ ] `Dockerfile`, `.dockerignore`, `deploy/compose.yaml`, `deploy/.env.example` exist as designed.
- [ ] `docker build -t uccc-genomics-app:dev .` succeeds on the host and in CI (new `container` job; no push).
- [ ] `docker compose -f deploy/compose.yaml --env-file deploy/.env.example config -q` exits 0 (CI and host).
- [ ] The image has no `.env`, `*.duckdb*` or key file: `docker run --rm --entrypoint sh uccc-genomics-app:dev -c 'find / -xdev \( -name ".env" -o -name "*.duckdb*" -o -name ".db_key*" -o -name ".deid_key*" \) 2>/dev/null'` prints nothing.
- [ ] The image runs as uid 10001 by default (`docker run --rm --entrypoint id uccc-genomics-app:dev`).
- [ ] Smoke run (below) answers `/api/health` with `Healthy`, serves `/` and `/discover`, with `--network none`.
- [ ] `tests/test_deploy.py` passes; `uv run pytest -q` passes.
- [ ] `systemd/genomics.service` has the guarded restart line right after `genomics all`.
- [ ] README runbook covers secrets from GSM, build, validate, up, logs, rollback and the monode
      follow-ups; ARCHITECTURE.md and AGENTS.md updated as above; `app.py` `--static` help updated.
- [ ] The real hostname appears in no committed file (`git grep` for it is empty).

## Test plan

1. `uv run pytest -q` (includes `tests/test_deploy.py`; needs Docker for the compose tests, skips
   them without it).
2. `docker build -t uccc-genomics-app:dev .`
3. `docker compose -f deploy/compose.yaml --env-file deploy/.env.example config -q`
4. Image hygiene: the `find` and `id` commands in the acceptance criteria.
5. Smoke run against a synthetic encrypted file in a temp dir (never `$DATA`):
   ```bash
   T=$(mktemp -d)   # under /data/davsean/tmp on this host
   uv run python -c "from uccc_genomics.config import connect; c = connect(deid=('$T/genomics.duckdb', '$T/.db_key')); c.execute('CREATE SCHEMA mart; CREATE TABLE mart.report AS SELECT 1 AS x'); c.close()"
   docker run -d --name uccc-smoke --network none -u "$(id -u):$(id -g)" \
     -v "$T/genomics.duckdb:/data/genomics.duckdb:ro" -v "$T/.db_key:/data/.db_key:ro" \
     uccc-genomics-app:dev --auth none --host 0.0.0.0 --port 8092 --static /app/web/dist
   sleep 3
   docker exec uccc-smoke python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8092/api/health').read()); print(u.urlopen('http://127.0.0.1:8092/').status, u.urlopen('http://127.0.0.1:8092/discover').status)"
   docker rm -f uccc-smoke; rm -rf "$T"
   ```
   Expect `{"status":"Healthy"}` and `200 200`. `--network none` also proves the encrypted read
   needs no extension download.
6. `cd web && bun install --frozen-lockfile && bun run typecheck && bun test` (n/a unless `web/`
   changed; it does not). Dashboard check: n/a.
7. Not run by agents: `docker compose up` against production, `systemctl` on the units.

## Risks

- **DNS:** the hostname does not resolve today (finding 3); bring-up waits for the monode record.
  If a `*.uccc` wildcard does exist outside Terraform and the local resolver is stale, the record
  step is a no-op; the runbook says to check with `dig` first.
- **Nightly restart:** a few seconds of downtime a day, and the app serves the previous day's file
  if `genomics all` fails (as intended). If someone `docker compose stop`s the container,
  `docker restart` starts it again at the next rebuild; `down` (removes it) is the way to keep it off.
- **Running as the host uid:** needed to read the mode-600 key; the container still sees only the
  two mounted files, without capabilities or privilege escalation.
- **Audit log retention:** rotated at 10 x 50 MB in json-file instead of journald's retention under
  systemd; moving the audit log to Postgres is the existing later issue.
- **No security-headers middleware** (HSTS etc.): monode's `security-headers@file` lives in an
  example file no service uses; not wired in, to avoid a router that breaks if that file goes.
  The app already sets a same-origin CSP in the built pages and `Secure`/`HttpOnly` cookies.
- **uvicorn behind Traefik** does not trust `X-Forwarded-*` from the docker network; nothing in the
  app reads the client address or scheme (redirects use `APP_BASE_URL`), so it is left alone.
- **Base image drift:** `python:3.12-slim-trixie` and the bun/uv tags are not digest-pinned; the
  host build is what runs, and rollback keeps the previous tag.
