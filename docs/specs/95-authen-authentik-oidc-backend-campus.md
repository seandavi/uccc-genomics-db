# Spec #95: `authen` Authentik OIDC backend (campus sign-in)

Issue #95 supersedes #40 (Zitadel). The identity provider is the central Authentik run from
seandavi/monode (`infrastructure/compose/authentik/README.md` § Contract for apps; the
`uccc-genomics` application, provider and `uccc-genomics-dashboard` group are seandavi/monode#130).
This spec adds an `authentik` backend behind `authen.user(request)`, the browser sign-in routes,
Bearer tokens for `/mcp`, and a signed-in user and "Sign out" in Discover.

Every example below is synthetic. Hostnames are placeholders (`<authentik-host>`, `<app-host>`,
`<tailnet-addr>`); real ones go in `.env` only (AGENTS.md). No patient data is involved.

## Goal

1. `genomics-app --auth authentik` signs a member of `AUTHENTIK_GROUP` in through Authentik
   (authorization code flow, PKCE, `state`, `nonce`), refuses everyone else, and keeps the user
   signed in with the app's own signed cookie for at most 8 hours.
2. Authorization is on the `groups` claim only, fail closed. Never on email or domain.
3. Users are keyed on `sub`. Saved cohorts, snapshots and the rate limit use it; email is a
   display label and goes in the audit log next to `sub`.
4. `/api/*` answers 401 (never a redirect) without a login; browser navigations to the static
   site redirect to `/auth/login`; Discover sends the user to sign in on a 401 and shows who is
   signed in with a "Sign out" button.
5. `/mcp` (and `/api/*`) accept `Authorization: Bearer <access token>` from the same provider,
   validated like the ID token.
6. `password` and `none` keep working unchanged for development; `access` keeps working.
7. README documents setup with the monode application.

## Non-goals

- Remote MCP clients, OAuth protected-resource metadata, Dynamic Client Registration (#30). MCP
  stays on the tailnet; how a local MCP client obtains an access token is not built here.
- Refresh tokens. The session ends after 8 hours and the user goes back through Authentik.
- RP-initiated logout with `id_token_hint` or `post_logout_redirect_uri`. Sign out clears the app
  cookie and sends the browser to Authentik's `end_session_endpoint`.
- Keeping the `#d=` share fragment when a signed-out user's **first** navigation is redirected by
  the server (the fragment never reaches the server). A 401 caught by Discover does keep it (see
  Design § Discover).
- A systemd unit, Traefik route or deploy for `genomics-app` (still development only).
- `bun run dev` with `--auth authentik` (the Vite proxy forwards `/api` only; use `password`).
- `genomics-cohort-api` does not get the `authentik` backend (it has no `/auth/*` routes).
- An Alembic migration: no column changes (see Design § Saved cohorts).
- A sign-in audit log.

## Contradictions with the design record (updated in this PR)

- `docs/ARCHITECTURE.md` decision 8 says the OIDC backend is Zitadel with "campus email required,
  checked again in the backend". The Authentik contract forbids authorizing on email or domain:
  the backend checks the group; campus-only (decision 12) is enforced by who is in the group
  (monode#130's policy adds campus Google sign-ins to it). Decision 8, decision 10 (client
  registration: Authentik, DCR stays off) and the Development paragraph are rewritten.
- `AGENTS.md` § Rules says only `/api/health` is open and `--auth password` "stands in until
  Zitadel". Under `--auth authentik`, `/auth/login`, `/auth/callback` and `/auth/logout` are also
  open (they are the sign-in itself). Update that bullet, and the Layout line for `authen`.

## Design

### Dependencies

No new package. `authen.py` already imports PyJWT, which arrives only through `mcp`. Declare it:
add `"pyjwt[crypto]>=2.10"` to `mcp/pyproject.toml` `dependencies` and run `uv lock` (the lock
already holds `pyjwt 2.13.0` and `cryptography`; only the dependency edge is added). HTTP calls use
stdlib `urllib.request`; JWKS caching uses `jwt.PyJWKClient` (it caches the key set for
`lifespan=300` s and refetches once on an unknown `kid`, verified in PyJWT 2.13
`jwks_client.py::get_signing_key`). Signed cookies are HS256 JWTs (`jwt.encode` / `jwt.decode`),
so no `itsdangerous` (not installed) and no Starlette `SessionMiddleware`.

### Configuration (`.env`, read by `authen.configure("authentik")`)

| Variable | Meaning | Check at start |
|---|---|---|
| `AUTHENTIK_ISSUER` | `https://<authentik-host>/application/o/uccc-genomics/` | set, ends with `/` |
| `AUTHENTIK_CLIENT_ID` | `uccc-genomics` | set |
| `AUTHENTIK_CLIENT_SECRET` | from GSM `uccc-genomics-authentik-client-secret` | set |
| `APP_BASE_URL` | e.g. `http://<tailnet-addr>:8092` or `https://<app-host>`; trailing `/` stripped | set, starts with `http://` or `https://` |
| `SESSION_SECRET` | signs the app's cookies; `python -c "import secrets; print(secrets.token_urlsafe(48))"` | set, at least 32 characters |
| `AUTHENTIK_GROUP` | optional, default `uccc-genomics-dashboard` | none |

`configure("authentik")` raises one `SystemExit` naming **every** missing or invalid variable,
e.g. `--auth authentik needs AUTHENTIK_CLIENT_SECRET, SESSION_SECRET (in .env)`. It does no network
I/O (discovery is lazy, so an Authentik outage doesn't stop the app or `/api/health`). The redirect
URI is `APP_BASE_URL + "/auth/callback"`; it must equal one of the Strict redirect URIs on the
Authentik provider. Cookies get `Secure` exactly when `APP_BASE_URL` starts with `https://`.

Add the six variables to `.env.example` with placeholder values, the secret ones commented
`# secret: real value only in .env` like `DATABASE_URL`.

### `mcp/src/uccc_genomics_mcp/authen.py`

Module docstring: replace the Zitadel lines; list `authentik` as the campus backend and say that
the `/auth/*` endpoints live here and `app.py` registers them.

```python
MODES = ("access", "password", "none", "authentik")
SESSION_COOKIE = "uccc_session"      # signed-in user; HS256 JWT, aud SESSION_AUD
LOGIN_COOKIE = "uccc_login"          # one sign-in in flight; HS256 JWT, aud LOGIN_AUD, Path=/auth
SESSION_AUD = "uccc-genomics-session"
LOGIN_AUD = "uccc-genomics-login"
SESSION_HOURS = 8
LOGIN_SECONDS = 600
OPEN_PATHS = ("/auth/login", "/auth/callback", "/auth/logout")   # open under authentik only

@dataclass(frozen=True)
class User:
    sub: str     # stable key: owner of saved cohorts and snapshots, rate-limit key
    email: str   # display label and audit log; may not be an email (see below)

AUTH = {"mode": "none", "team": None, "aud": None, "jwks": None, "user": None, "hash": None,
        "issuer": None, "client_id": None, "client_secret": None, "base_url": None,
        "session_secret": None, "group": None, "oidc": None}
```

Functions (existing ones keep their behaviour except the return type of `user`):

- `configure(mode: str) -> None` — adds the `authentik` branch above. `AUTH["oidc"]` (discovery)
  and `AUTH["jwks"]` (a `PyJWKClient`) start as `None` and are filled on first use.
- `user(request: Request) -> User` — `none`: `User("dev@localhost", "dev@localhost")`;
  `password`: `User(name, name)`; `access`: `User(email, email)` (the Access `email` claim, as
  today, so access-mode owners don't change); `authentik`: `_authentik(request)`.
- `challenge() -> dict` — unchanged (Basic header under `password`, else `{}`).
- `login_path() -> str | None` — `"/auth/login"` under `authentik`, else `None`.
- `open_path(path: str) -> bool` — `path in OPEN_PATHS` under `authentik`, else `False`.
- `login(request: Request) -> Response` (GET `/auth/login`).
- `callback(request: Request) -> Response` (GET `/auth/callback`).
- `logout(request: Request) -> Response` (POST `/auth/logout`).

Private helpers (names fixed so tests and reviewers can find them):

- `_get_json(url: str) -> dict` and `_post_form(url: str, form: dict[str, str]) -> dict`:
  `urllib.request.urlopen(urllib.request.Request(...), timeout=10)`, JSON body. They call
  `urllib.request.urlopen` by attribute (not `from urllib.request import urlopen`), so tests
  replace it in one place, the same place `PyJWKClient.fetch_data` calls.
- `_oidc() -> dict`: once, `_get_json(AUTH["issuer"] + ".well-known/openid-configuration")`;
  require `issuer == AUTH["issuer"]` and the keys `authorization_endpoint`, `token_endpoint`,
  `jwks_uri` (else `RuntimeError("identity provider misconfigured")`); cache in `AUTH["oidc"]` and
  set `AUTH["jwks"] = jwt.PyJWKClient(doc["jwks_uri"], timeout=10)`. A failure is not cached.
- `_verify(token: str, nonce: str | None) -> dict`: the shared check for ID and access tokens.
  `key = AUTH["jwks"].get_signing_key_from_jwt(token).key`; `jwt.decode(token, key,
  algorithms=["RS256"], audience=AUTH["client_id"], issuer=AUTH["issuer"],
  options={"require": ["exp", "iat", "sub"]})`. When `nonce` is not `None` the claim must be a
  string equal to it (`hmac.compare_digest`; missing means refused). Then `_require_group`. Any
  `jwt.PyJWTError` (including `PyJWKClientError` for a fetch failure or an unknown `kid`), a
  discovery failure, or a group failure becomes `PermissionError` with a short fixed or PyJWT
  message; never the token.
- `_require_group(claims: dict) -> None`: `groups = claims.get("groups")`; refuse unless it is a
  `list` containing `AUTH["group"]` exactly.
- `_display(claims: dict) -> str`: `claims.get("email") or claims.get("preferred_username") or
  claims["sub"]` (ORCID sign-ins carry no email; nothing verifies an email; it is never used to
  authorize).
- `_sign(claims: dict, aud: str, seconds: int) -> str` / `_unsign(token: str, aud: str) -> dict`:
  HS256 with `AUTH["session_secret"]`, `iat`/`exp` set by `_sign`; `_unsign` requires `exp` and
  checks `aud`, so a login cookie is never accepted as a session and vice versa.
- `_safe_next(raw: str | None) -> str`: `raw` if it starts with `/`, not `//`, contains no `\`, no
  ASCII control character, and does not start with `/auth/`; otherwise `/`. Fragments (`#d=...`)
  are kept.
- `_cookie(response, name, value, max_age, path)`: `set_cookie(..., httponly=True,
  samesite="lax", secure=AUTH["base_url"].startswith("https://"))`.

`_authentik(request) -> User`:

1. If `Authorization` is `Bearer <token>` (scheme case-insensitive, token non-empty): `claims =
   _verify(token, None)`; return `User(claims["sub"], _display(claims))`. A bad Bearer token is
   refused; it does not fall back to the cookie.
2. Else the `uccc_session` cookie: `s = _unsign(cookie, SESSION_AUD)`, return
   `User(s["sub"], s["email"])`. Missing → `PermissionError("not signed in")`; bad signature or
   expired → `PermissionError("session expired")`.

The session cookie's claims are exactly `aud`, `sub`, `email`, `iat`, `exp` (`exp = iat + 8 h`,
not extended on use). `groups` is never stored; removing someone from the group takes effect at
their next sign-in, at most 8 hours later (contract rule 7). Bearer requests re-check the group on
every call (it is in the token).

`login(request)` (sync; runs in the threadpool):

1. `oidc = _oidc()`; on failure `502` HTML "The identity provider is not reachable."
2. `state = secrets.token_urlsafe(32)`, `nonce = secrets.token_urlsafe(32)`, `verifier =
   secrets.token_urlsafe(48)`, `challenge = base64url(sha256(verifier))` without `=` padding.
3. Set `uccc_login` = `_sign({"state", "nonce", "verifier", "next": _safe_next(query "next")},
   LOGIN_AUD, LOGIN_SECONDS)`, `Max-Age=600`, `Path=/auth`.
4. `302` to `authorization_endpoint?` + `urlencode({"response_type": "code", "client_id",
   "redirect_uri", "scope": "openid email profile", "state", "nonce", "code_challenge",
   "code_challenge_method": "S256"})`.

`callback(request)` (sync). Every refusal is a small fixed HTML page (`HTMLResponse`, text from
constants only, never request values) with a link to `/auth/login`, and clears `uccc_login`:

1. Query `error` present → `403` "Sign-in was refused." (Authentik refuses non-members before a
   code is issued: contract rule 2.)
2. `uccc_login` missing, bad or expired, or query `state` missing or not equal to the cookie's
   (`hmac.compare_digest`), or `code` missing → `400` "Sign-in expired or was started elsewhere;
   try again."
3. `_post_form(token_endpoint, {"grant_type": "authorization_code", "code", "redirect_uri",
   "code_verifier", "client_id", "client_secret"})` (client_secret_post, which Authentik
   accepts). `HTTPError`/`URLError`/no `id_token` in the answer → `502` "Sign-in failed at the
   identity provider."
4. `claims = _verify(id_token, cookie nonce)`; `PermissionError` → `403` "You don't have access to
   this app." (covers bad signature, `iss`, `aud`, `exp`, nonce, and a missing or other group).
5. Success: `303` to the cookie's `next`; set `uccc_session` = `_sign({"sub": claims["sub"],
   "email": _display(claims)}, SESSION_AUD, 8 h)`, `Max-Age=28800`, `Path=/`; clear `uccc_login`.

`logout(request)`: clear `uccc_session` (`Path=/`, `Max-Age=0`); return JSON `{"url": u}` with
`u` = `end_session_endpoint` from `_oidc()` if present, else `"/"` (also `"/"` if discovery fails).
It needs no login (an expired user can still sign out). Discover navigates to `url`.

The access token for `/mcp`: Authentik issues JWT access tokens signed with the provider key,
`iss` and `aud` as the ID token, and the scope claims (`groups` with `profile`). If a token lacks
`groups` it is refused (fail closed), so a wrong assumption here can only lock out, never let in.

### `mcp/src/uccc_genomics_mcp/app.py`

- `RequireUser.__call__`: let through `lifespan`, `GET /api/health` (as today) and any HTTP path
  where `authen.open_path(path)`. On `PermissionError`:
  - if `authen.login_path()` is set, the method is `GET`, and the path neither starts with
    `/api/` nor equals `/mcp`: `302` to `login_path + "?next=" + quote(path + ("?" + query if
    query else ""), safe="")` (a browser navigation to the static site);
  - otherwise `401` JSON `{"detail": str(e)}`, plus `"login": login_path` when it is set, with
    `headers=authen.challenge()` as today.
  On success store the `authen.User` in `scope["state"]["user"]`.
- `user(request) -> authen.User` and `_mcp_user(ctx) -> authen.User` (same lookups, new type).
- Every route and tool that took `email: str = Depends(user)` / `_mcp_user(ctx)` now has
  `u: authen.User`. `rate_limit(key: str)` is called with `u.sub`. `run_count`, `run_pivot`,
  `run_save`, `run_saved_apply`, `run_snapshot` take `u: authen.User` instead of `email: str` and
  pass `u.sub` to `saved.*` and `rate_limit`, `u` to `audit`.
- `audit(u: authen.User, surface, endpoint, d, patients)`: the JSON line gains `"sub": u.sub` next
  to `"email": u.email` (both keys, in that order: `t`, `sub`, `email`, ...).
- New response model and route (in OpenAPI):
  ```python
  class Me(BaseModel):
      sub: str
      email: str
      sign_out: bool   # true under --auth authentik: Discover shows "Sign out"

  @application.get("/api/me")
  def get_me(u: authen.User = Depends(user)) -> Me:
      return Me(sub=u.sub, email=u.email, sign_out=authen.AUTH["mode"] == "authentik")
  ```
  It returns only the caller's own identity: no counts, nothing from the de-id file.
- In `app()`, when `authen.AUTH["mode"] == "authentik"`, before the static mount:
  `application.add_api_route("/auth/login", authen.login, methods=["GET"],
  include_in_schema=False, response_model=None)`, likewise `/auth/callback` (GET) and
  `/auth/logout` (POST). Under other modes these paths are not routed and not open (they fall to
  `RequireUser` like any other path).
- `main()`: `--auth` help names `authentik: campus sign-in through Authentik (AUTHENTIK_*,
  APP_BASE_URL, SESSION_SECRET in .env)`.
- After the model change run `cd web && bun run gen` (rewrites `web/openapi.json` and
  `web/src/api.gen.ts`); `test_openapi_snapshot` pins it.

### `mcp/src/uccc_genomics_mcp/saved.py` (saved cohorts)

Parameter rename only, no SQL or schema change: every `email` parameter becomes `owner` (it now
receives `User.sub`). Columns keep their names and types: `cohort.owner`, `snapshot.created_by`
and `cohort_version.created_by` (text) now hold `sub` under `authentik`. The module docstring says
so. No Alembic revision.

Migration path for existing owners (they hold whatever the old backend returned, e.g. `APP_USER`
under `password`): after signing in, the user reads their `sub` from `GET /api/me`, and a person
runs, once, against the app's database (README gets this block):

```bash
psql "$DATABASE_URL" -v old='<old owner>' -v new='<sub from /api/me>' <<'SQL'
BEGIN;
UPDATE cohort   SET owner      = :'new' WHERE owner      = :'old';
UPDATE snapshot SET created_by = :'new' WHERE created_by = :'old';
COMMIT;
SQL
```

`cohort_version.created_by` is provenance, not ownership, and is left as is.

### `mcp/src/uccc_genomics_mcp/cohort_api.py`

`authed()` returns `authen.user(request).email` (log line unchanged). `--auth` choices become
`[m for m in authen.MODES if m != "authentik"]`.

### Discover (`web/`)

- `web/src/types.ts`: `export type Me = S["Me"];`.
- `web/src/transport.ts` (still the only `fetch`):
  - `export function signInAt(login: string): void` — `window.location.assign(login + "?next=" +
    encodeURIComponent(location.pathname + location.search + location.hash))`.
  - The request helper: on a 401 whose JSON body has `login` as a string starting with `/`, call
    `signIn(body.login)` and still throw the `TransportError(…, 401)`.
  - `fetchTransport(fetchImpl: FetchLike = fetch, signIn: (login: string) => void = signInAt)`.
  - `export interface Account { me(): Promise<Me>; signOut(): Promise<void> }` and
    `fetchAccount(fetchImpl: FetchLike = fetch, signIn = signInAt, navigate: (url: string) => void
    = (u) => window.location.assign(u)): Account`. `me()` is `GET /api/me` through the same
    helper; `signOut()` is `POST /auth/logout`, then `navigate(body.url)`.
- `web/src/App.tsx`: `App({transport, account}: {transport: Transport; account?: Account})`. With
  `account`, on start `account.me()`; once it resolves, the header ends with `<span
  className="who">{me.email}</span>` and, if `me.sign_out`, `<button type="button">Sign
  out</button>` calling `account.signOut()`. A failed `me()` shows nothing extra. Without
  `account` (existing tests) nothing changes.
- `web/src/main.tsx`: pass `account={fetchAccount()}`.
- The CSP stays as is: sign-out is a `fetch` plus a navigation, not a form (`form-action 'none'`).

### Docs

- `README.md` § Cohort app: `--auth access|password|none|authentik`; a "Campus sign-in
  (Authentik)" block: the monode application (monode#130: slug `uccc-genomics`, confidential,
  Strict redirect URIs `<APP_BASE_URL>/auth/callback` per deployment, group binding
  `uccc-genomics-dashboard`), fetching the client secret from GSM into `.env` without printing it
  (`gcloud secrets versions access latest --secret=uccc-genomics-authentik-client-secret
  --project=<gsm-project>`), generating `SESSION_SECRET`, the env table above, the 8-hour session
  and group-freshness rule, the member / non-member check (contract step 4), the `/api/me` and
  owner migration block, and that the audit line now carries `sub` and `email`.
- `docs/ARCHITECTURE.md` decisions 8 and 10 and § Development; `AGENTS.md` rule bullet and Layout
  line, as listed in "Contradictions".
- `mcp/README.md` needs no change.

### Data and privacy

No change to `deid.py`, the pipeline, `mart.*` or any count path: `research_id` and `report_id`
are untouched. No new output carries data from the de-id file: `/api/me` returns the caller's own
`sub` and display label, `/auth/*` returns redirects, a fixed HTML page or a URL. Suppression,
the whole-cohort rule and the rate limit are unchanged (the limit is keyed on `sub`). Tokens,
codes, the client secret, `SESSION_SECRET` and cookie values are never logged or put in an error
body.

## Acceptance criteria

- [ ] `authen.configure("authentik")` with any of the five required variables missing, a
      `SESSION_SECRET` under 32 characters, an issuer without a trailing `/`, or an
      `APP_BASE_URL` not starting with `http(s)://` raises `SystemExit` naming each problem.
- [ ] Against a fake issuer, `GET /auth/login` → 302 to its `authorization_endpoint` with
      `response_type=code`, the client ID, `redirect_uri=<APP_BASE_URL>/auth/callback`, a scope
      containing `openid` and `profile`, `state`, `nonce`, `code_challenge_method=S256`; and sets
      `uccc_login` (HttpOnly, SameSite=Lax, Path=/auth).
- [ ] A member's callback → 303 to `/` (or the safe `next`), sets `uccc_session` (HttpOnly,
      SameSite=Lax, `Max-Age=28800`; `Secure` only with an `https://` base URL) whose claims are
      exactly `aud, sub, email, iat, exp` with `exp - iat == 28800`; then `GET /api/me` is
      `{sub, email, sign_out: true}` and `POST /api/cohort` is 200 with an audit line carrying
      that `sub` and `email`.
- [ ] The token request sent the PKCE verifier matching the challenge, the redirect URI and the
      client credentials.
- [ ] Callback refuses (no `uccc_session` set): wrong `iss`, wrong `aud`, expired, signed by
      another key, HS256-signed, no `groups`, another group only, missing nonce, wrong nonce
      (403); bad or missing `state`, missing `uccc_login`, missing `code` (400); `error` in the
      query (403); token endpoint error (502).
- [ ] `next=//evil.example`, `next=https://evil.example`, `next=/auth/logout` all land on `/`;
      `next=/x?y=1#d=abc` is kept.
- [ ] A forged session cookie (other secret), an expired one, and a `uccc_login` value used as
      `uccc_session` are refused (401 on `/api/*`).
- [ ] Without login under `authentik`: `/api/*` and `/mcp` → 401 JSON with `"login":
      "/auth/login"` and no `Location`; `GET /`, `/index.html`, `/no/such/path?q=1` → 302 to
      `/auth/login?next=<quoted path and query>`. Every `GATED` route (plus `/api/me`) accepts the
      session cookie. `/api/health` and the three `/auth/*` paths need no login.
- [ ] Under `password`, `/auth/login` is not open (401 with the Basic challenge), and the existing
      `GATED` test passes unchanged except for the added `/api/me`.
- [ ] `/mcp` with a valid Bearer access token runs `count` (200, not `isError`); wrong `aud`,
      expired, no group or another group → 401. A token signed with a rotated key (new `kid`)
      after the first JWKS fetch is accepted after one refetch.
- [ ] `POST /auth/logout` (no login needed) clears `uccc_session` and returns the fake issuer's
      `end_session_endpoint` as `url`.
- [ ] Saved cohorts under `authentik` are owned by `sub` (`cohort.owner` and
      `snapshot.created_by` hold it).
- [ ] Discover: a 401 with `login` calls `signIn("/auth/login")`; a 401 without it does not;
      `fetchAccount().signOut()` POSTs `/auth/logout` and navigates to the returned `url`; App
      with an `account` shows the email and "Sign out" (only when `sign_out`).
- [ ] `web/openapi.json` and `web/src/api.gen.ts` regenerated; docs updated as listed.
- [ ] `uv run pytest -q`, `cd web && bun install --frozen-lockfile && bun run typecheck && bun
      test` pass. Dashboard check n/a (nothing under `dashboard/`).

## Test plan

No network, no `$DATA`, no PHI file, no real de-id file. The app tests reuse `tests/test_app.py`'s
synthetic mart fixtures (`ids`, `build_mart`/`write_mart`/`use_mart` from `tests/test_cohort.py`).

New `tests/test_authen.py`:

- `FakeIssuer`: an RSA key (`cryptography`, 2048 bits) with `kid` `k1`, issuer
  `https://id.example.test/application/o/uccc-genomics/`, endpoints under it (`authorize/`,
  `token/`, `jwks/`, `end-session/`). Its `urlopen(req, timeout=None, context=None)` serves the
  discovery document, the JWKS (`jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)`
  plus `kid`, `alg`, `use`) and the token endpoint, returning `io.BytesIO(json)` (a context
  manager with `.read()`). The token endpoint checks the form (code issued by `authorize(...)`,
  `sha256(code_verifier)` = the stored challenge, `redirect_uri`, `client_id`, `client_secret`)
  and returns `{"id_token", "access_token", "token_type": "Bearer"}`, or raises
  `urllib.error.HTTPError(…, 400, …)`. It counts JWKS fetches. `rotate()` swaps in a new key with
  `kid` `k2`. Token claims default to `iss`, `aud="uccc-genomics"`, `sub="synthetic-sub-1"`,
  `email="member@example.edu"`, `groups=["uccc-genomics-dashboard"]`, `iat`, `exp=now+300`, and
  the authorize nonce; each test overrides one.
- Fixture `oidc(ids, monkeypatch, tmp_path)`: `monkeypatch.setattr(urllib.request, "urlopen",
  issuer.urlopen)`, `monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))`, set the env
  (`APP_BASE_URL=http://testserver`, a 48-character `SESSION_SECRET`, …), `DATABASE_URL` unset,
  `authen.configure("authentik")`, then `TestClient(app.app(static_dir))` with
  `follow_redirects=False`. Helper `sign_in(c, **claims)` runs login → fake authorize → callback.
- One test per acceptance bullet above (configure errors; login redirect; member sign-in and
  audit; each callback refusal, parametrized; `next` handling, parametrized; forged/expired/
  cross-audience cookies; 401-vs-302 over `test_app.GATED` + `/api/me`; Bearer on `/mcp` incl.
  key rotation; logout).

Changes to existing tests:

- `tests/test_app.py`: add `("GET", "/api/me")` to `GATED`; `test_password_auth_routes_closed`
  (`/auth/login` → 401 Basic under `password`); `test_audit` and `test_access_backend` also assert
  the `sub` key (equal to the user under `password`/`access`).
- `tests/test_saved.py`: `sclient`'s fake returns `authen.User(h, h)`; add one test that a cohort
  saved by `User("sub-a", "a@example.edu")` has `cohort.owner == "sub-a"` and is invisible to
  `User("sub-b", "a@example.edu")` (same email, other `sub`). Runs only with `TEST_DATABASE_URL`.
- `tests/test_cohort_api.py`: unchanged; it must still pass (email in the log line).
- `web/src/transport.test.ts`: the 401 `login` cases and `fetchAccount` (`me`, `signOut`) with the
  existing `stub` and recorder functions for `signIn`/`navigate`.
- `web/src/app.test.tsx`: one render with a stub `account` resolving `{sub, email, sign_out:
  true}` shows the email and "Sign out"; with `sign_out: false`, no button.

Commands: `uv run pytest -q`; `TEST_DATABASE_URL=... uv run pytest -q tests/test_saved.py`;
`cd web && bun install --frozen-lockfile && bun run gen && bun run typecheck && bun test`.

## Risks

- **Seam.** `authen.user` now returns `User`, and every caller of it changes (`app.py`,
  `cohort_api.py`, the `test_saved.py` fake). A missed caller that keeps treating the result as a
  string would put `User(...)` reprs in logs or Postgres; the audit and saved tests catch it.
- **Owner semantics.** `cohort.owner` changes meaning (email/username → `sub`) without a schema
  change. Existing rows stay readable only after the documented `UPDATE`. On this host the app is
  still development-only, so the expected affected rows are the developer's own.
- **Access token shape.** The Bearer path assumes Authentik access tokens are RS256 JWTs with
  `aud` = client ID and `groups`. If not, Bearer is refused (fail closed); browser sign-in is
  unaffected. Check once against the real provider with a member token.
- **JWKS refetch on unknown `kid`.** A caller can make each Bearer request with a random `kid`
  trigger one JWKS fetch (`PyJWKClient` behaviour). Tolerable while `/mcp` is on the tailnet;
  revisit with remote MCP (#30).
- **Redirect loop on misconfiguration.** If `APP_BASE_URL` is `https://` but the app is reached
  over `http://`, the `Secure` session cookie is never sent back, so every `/api` call 401s and
  Discover re-enters sign-in. README says `APP_BASE_URL` must be the URL users open.
- **Two tabs signing in at once** overwrite `uccc_login`; the earlier tab's callback gets the 400
  "try again" page.
- **Group freshness.** Removal from the group or deactivation takes effect at the next sign-in, up
  to 8 hours (contract rule 7); Bearer tokens re-check it each call.
- **Sign-out is app-local plus Authentik's invalidation flow.** If the Authentik session survives
  that flow, the next visit signs the user in again silently; that is standard SSO behaviour.
