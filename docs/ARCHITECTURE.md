# Architecture: the cohort site

Decided 2026-10-25. This is the target for the campus cohort site that replaces the cohort page on
the public Cloudflare dashboard. `dashboard/COHORT_DISCOVERY.md` is the product design (questions,
cohort definition, mart, page, assistant, privacy additions); this file records the architecture
and the decisions behind it. Tracking issue: #23.

```
        React app (Discover)                    MCP App (same React builder, ui:// resource)
             │ apply(op) over fetch                  │ apply(op) over MCP tool calls
             ▼                                       ▼
   FastAPI:  /api/*  REST      /api/chat         /mcp  MCP tools
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
2. **Edits are operations.** `add_criterion`, `remove_criterion`, `set_mode`, `set_population`,
   `set_breakdown`, … Clicks, MCP calls and chat turns all send operations; applying one makes a
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
   against today's data, except grant snapshots, which store counts with the data date.
8. **Auth behind `authen.user(request)`.** Backends today: `access` (Cloudflare Access JWT),
   `password` (one local account, while developing), `none`. Zitadel (OIDC, campus email
   required, checked again in the backend) becomes another backend; callers do not change.
9. **Chat inside the site** (`/api/chat`): a server-side model loop whose only tools are the
   cohort module's operations and queries. It never states a number a tool did not return. The
   provider waits on the DUA question (`COHORT_DISCOVERY.md` §5.2).
10. **MCP App** as a second host for the builder, once REST, MCP and the React app exist. Remote
    MCP clients (Claude.ai) need the MCP endpoint reachable from the internet and OAuth client
    registration in Zitadel (dynamic registration is off by default there; verify the version).
11. **Suppression applies to logged-in users too.** Campus login decides who may ask, not what a
    count may reveal. Saved, editable cohorts make differencing easier, so §3.6's rules apply
    and requests are rate-limited per user.
12. **The app is campus-only.** The public Cloudflare dashboard shrinks to high-level totals
    (patients, diseases, vendors, years); everything else moves behind login.

## Development

The app runs on the pipeline host, bound to its tailnet address, with `--auth password`, so
progress is visible at `http://<host>:<port>` from the tailnet. No `tailscale serve`, no
deploys. Production hosting (Docker Compose behind Traefik, Zitadel) comes after the app works.
