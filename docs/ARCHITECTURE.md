# Architecture: the cohort site

Decided 2026-10-25. This is the target for the campus cohort site that replaces the cohort page on
the public Cloudflare dashboard. `dashboard/COHORT_DISCOVERY.md` is the product design (questions,
cohort definition, mart, page, assistant, privacy additions); this file records the architecture
and the decisions behind it. Tracking issue: #23.

```
        React app (Discover)                    MCP App (same React builder, ui:// resource)
             │ apply(op) over fetch                  │ apply(op) over MCP tool calls
             ▼                                       ▼
   FastAPI:  /api/*  REST      /api/chat         /mcp  MCP tools      /api/public/summary (open)
             └──────────────┬──────────────────────────┘
                     authen.user(request) -> who            (one check for every surface)
                            │
                cohort module: ops -> definition -> compile -> run -> suppress -> typed results
                     │                                   │
        genomics.duckdb (de-id, read-only, mart.*)   Postgres: saved cohorts, versions, audit
```

## Decisions

1. **One cohort definition, one module.** The definition (`COHORT_DISCOVERY.md` §3.1) is a
   versioned Pydantic model; its JSON Schema is the REST body, the MCP tool input and the
   frontend's types. Normalised (sorted lists, upper-case genes) and hashed, it gets a stable
   `cohort_id`. The `cohort` module is the only code that turns a definition into SQL, and every
   count it returns has passed `suppress()`. Neither the browser nor a model ever sends SQL.
   The package is `mcp/src/uccc_genomics_mcp/cohort/` (#34).
2. **Edits are operations.** `add_criterion`, `remove_criterion`, `set_mode`, `set_population`,
   `set_breakdown`, `set_scope`, … Clicks, MCP calls and chat turns all send operations; applying one makes a
   new immutable version. History, undo, reviewable assistant proposals and an audit of intent
   come from this.
3. **A mart under the compiler.** `deid` builds `mart.report` and `mart.fact`
   (`COHORT_DISCOVERY.md` §3.2) after the data-readiness normalisation (significance tier,
   HER2 calls, consequence case). Every criterion kind compiles to the same template over it.
4. **REST and MCP are built together** as thin layers over the module, and one test runs every
   operation through both and requires identical results. The free-SQL `query` tool stays on
   the internal tailnet MCP server only.
5. **FastAPI** for the new service (Starlette underneath, so the existing pieces port).
   The current `genomics-cohort-api` keeps serving the public dashboard until that page is
   retired.
6. **React** (TypeScript, Vite, bun) for the Discover app, served same-origin by the FastAPI
   service. Its transport sits behind one `apply(op)` seam, so the MCP App reuses it.
7. **Postgres** for saved cohorts, versions and the audit log: one database on the host's shared
   cluster, SQLAlchemy async + asyncpg. Definitions hold no patient data; counts are recomputed
   against today's data, except grant snapshots, which store counts with the data date. Tables
   (#36, Alembic migrations, URL from `DATABASE_URL`): `cohort_version` (content-addressed),
   `cohort`, `cohort_revision` (append-only chain; revert appends a copy) and `snapshot` (the
   suppressed `CountResult`). Every read and write is scoped to the owner. The exception is
   `cohort_version`: any logged-in user can resolve a `cohort_id`, so the lookup shows whether
   anyone has ever saved a given definition (an existence oracle). That is accepted: users are
   campus-only and no patient data or counts are revealed, and a keyed `cohort_id` would mean
   another key file to manage. Revisit if the audience widens (#56). The query audit log stays one
   JSON line on stdout for now; moving it to Postgres is a later issue. The honest-broker tables
   (IRB registry, requests, reviews, releases; #132) live there too, and hold study ids only, never
   identifiers: see `docs/HONEST_BROKER.md`.
8. **Auth behind `authen.user(request)`.** Backends today: `access` (Cloudflare Access JWT),
   `password` (one local account, while developing), `none`, and `authentik` (#95): OIDC through
   the central Authentik (seandavi/monode), authorization code flow with PKCE, a signed app cookie
   for at most 8 hours, Bearer access tokens for `/mcp`. It authorizes on the `groups` claim only
   (the Authentik contract forbids deciding on email or domain), so campus-only (decision 12) is
   enforced by who is in the group, not by an email check in the backend. Users are keyed on
   `sub`; email is a display label. `authen.user` returns `User(sub, email)`; callers use `sub`.
   This replaces the earlier Zitadel plan (#40).
9. **Chat inside the site** (`/api/chat`): a server-side model loop whose only tools are the
   cohort module's operations and queries. It never states a number a tool did not return. The
   provider waits on the DUA question (`COHORT_DISCOVERY.md` §5.2).
10. **MCP App** as a second host for the builder, once REST, MCP and the React app exist. Remote
    MCP clients (Claude.ai) need the MCP endpoint reachable from the internet and OAuth client
    registration in Authentik (Dynamic Client Registration stays off there; #30).
11. **Suppression applies to logged-in users too.** Campus login decides who may ask, not what a
    count may reveal. Saved, editable cohorts make differencing easier, so §3.6's rules apply
    and requests are rate-limited per user.
12. **The app is campus-only, with a public landing page.** The public totals (patients, reports,
    tumor types, vendors, years) are the campus app's landing page (`/`, fed by the open
    `GET /api/public/summary`: fixed aggregates, floored at 5 and rounded to 10, #41); everything
    else, Discover included (`/discover`), is behind login. The Cloudflare dashboard and
    `genomics-cohort-api` retire in a follow-up once production hosting is live.

## Development

The app runs on the pipeline host, bound to its tailnet address, with `--auth password` or
`--auth authentik` (campus sign-in through Authentik, `APP_BASE_URL` set to the tailnet URL), so
progress is visible at `http://<host>:<port>` from the tailnet (Discover at `/discover`, the landing page at `/`). No `tailscale serve`, no
deploys. The service is `genomics-app` (`mcp/src/uccc_genomics_mcp/app.py`, #35). Production runs the same app in a container behind
Traefik (`Dockerfile`, `deploy/compose.yaml`, #129; README § Production (container)); its public
router does not route `/mcp`, so remote MCP (decision 10) needs a routing change when it lands.

The app (Discover) is built from `web/` and served by `genomics-app --static web/dist` (#37), so it
shares the origin and the login of `/api/*`.
