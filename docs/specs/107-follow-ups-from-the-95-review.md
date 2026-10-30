# Spec #107: follow-ups from the #95 review

Issue #107 lists eight minor/nit findings from the #95 review (the `authentik` backend in
`mcp/src/uccc_genomics_mcp/authen.py`, its wiring in `app.py`, and Discover's sign-in/sign-out).
All are open on `origin/main` at 6680867. This spec fixes all eight. No patient data is involved;
hostnames, subs and emails below are the synthetic ones `tests/test_authen.py` already uses.

| Finding | Where | Fix (section below) |
|---|---|---|
| code-r0-1 | `authen.callback`, `hmac.compare_digest` on `str` | Compare bytes |
| code-r0-2 | `authen._scrypt` comment | Reword |
| security-r0-1 | `authen._oidc`, `PyJWKClient` refetch per unknown `kid` | Throttle JWKS and discovery fetches |
| security-r0-3 | `web/src/transport.ts` `login.startsWith("/")` | Same-site check like `_safe_next` |
| ux-r0-3 | `authen.callback` one 403 text for every `_verify` failure; `_PAGE` markup | Separate refusals; page head |
| ux-r0-4 | `authen.challenge()` empty under authentik | `WWW-Authenticate: Bearer`; 503 on provider outage |
| ux-r0-5 | `web/src/App.tsx` swallowed sign-out error; bare email | Show error; "Signed in as" |
| ux-r1-1 | refusal pages are a dead end | Fixed sentence naming the group |

## Goal

1. `/auth/callback?code=x&state=é` with a valid `uccc_login` cookie is the fixed 400 page and
   clears `uccc_login` (today: unhandled `TypeError`, 500).
2. Unauthenticated callers cannot make the server fetch from Authentik more than once per
   `PROVIDER_RETRY_SECONDS = 30` s: neither with Bearer tokens carrying random `kid`s nor while
   discovery or the JWKS endpoint is failing. Concurrent requests make one fetch, not one each.
3. Under `--auth authentik`, a 401 JSON answer carries `WWW-Authenticate: Bearer
   realm="uccc-genomics"` (RFC 6750 § 3), and a Bearer token that can't be checked because the
   provider is unreachable gets 503 with `Retry-After: 30`, not 401.
4. The callback says "no access" only when the group check fails; other token failures say
   "Sign-in failed; try again."; a provider outage says the provider is not reachable. Both
   "no access" and "Sign-in was refused." pages name the group and who to ask, from configuration
   only, never from request values.
5. The fixed HTML pages have `<html lang="en">`, a viewport meta and an `<h1>`.
6. Discover follows a 401's `login` only when it is a same-site path (`/x`, not `//host`, not
   `/\host`); a failed sign-out shows an error; the signed-in label reads "Signed in as …" to a
   screen reader.

## Non-goals

- The `access` backend keeps `jwt.PyJWKClient` unchanged. Its tokens come through Cloudflare
  Access and the Worker, and `genomics-cohort-api` (the production path) is not touched here.
- No `error="invalid_token"` parameter in the challenge; `realm` only. No `WWW-Authenticate` on
  the HTML sign-in page `signin_page()` (browsers don't act on a Bearer challenge; unchanged).
- The 401 body's `"login": "/auth/login"` stays on `/mcp` too (#30 decides what MCP clients get).
- No change to how sessions, cookies, `state`/`nonce`/PKCE, `_safe_next` or the group rule work.
- No new dependency (`threading`, `html` are stdlib; PyJWT 2.13 is already declared).
- Nothing under `src/uccc_genomics/`, `dashboard/` or `systemd/` changes; no pipeline, de-id,
  `mart.*` or count-path change. **`research_id` and `report_id` stability is not affected.** No
  new output leaves the de-id file: every changed response carries a fixed string, the configured
  group name, or a status code, so no small-cell rule applies.
- No change to the design docs' decisions. `docs/ARCHITECTURE.md` decision 10 already sends
  remote-MCP concerns to #30; this spec only adds the throttle that #95's Risks deferred.

## Design

Files: `mcp/src/uccc_genomics_mcp/authen.py`, `mcp/src/uccc_genomics_mcp/app.py`,
`web/src/transport.ts`, `web/src/App.tsx`, `README.md`, and the tests listed in the Test plan.
`web/openapi.json` and `web/src/api.gen.ts` do not change (no model or route change); `bun run
typecheck` confirms it.

### `authen.py`

New imports: `html`, `threading`. New constants and exceptions next to the existing ones:

```python
PROVIDER_RETRY_SECONDS = 30   # at most one discovery or JWKS fetch per this long (#107)
ACCESS_HELP = ("Access is limited to members of the {group} group; "
               "ask the UCCC genomics team to be added.")
UNREACHABLE = "The identity provider is not reachable; try again."


class NotInGroup(PermissionError):
    """The token is good but the caller is not in AUTH["group"]."""


class ProviderUnavailable(PermissionError):
    """Discovery or the JWKS could not be fetched (or failed under PROVIDER_RETRY_SECONDS ago)."""
```

Both subclass `PermissionError`, so every existing `except PermissionError` (`RequireUser`,
`cohort_api.authed`) still refuses; callers that care catch the subclass first.

`AUTH` gains `"oidc_failed_at": None`; `configure("authentik")` resets it with
`oidc_failed_at=None` alongside `oidc=None, jwks=None`.

**code-r0-2.** `_scrypt` comment becomes:
`# ponytail: ~50 ms per request at these settings; fine for one local user (password is a development stand-in).`

**security-r0-1: the JWKS client.** A subclass of `jwt.PyJWKClient`, used only by `_oidc()`:

```python
class _JWKS(jwt.PyJWKClient):
    """PyJWKClient that fetches the key set at most once per PROVIDER_RETRY_SECONDS, whatever asks
    (an unknown kid, a retry after a failed fetch), so unauthenticated Bearer tokens can't make the
    server hammer the provider (#107). Lookups take a lock, so a burst waits for one fetch."""

    def __init__(self, uri: str) -> None:
        super().__init__(uri, timeout=10)
        self.fetched_at, self.failed = float("-inf"), False
        self._lock = threading.Lock()

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            return super().get_signing_key(kid)

    def fetch_data(self):
        if time.monotonic() - self.fetched_at < PROVIDER_RETRY_SECONDS:
            if self.failed:
                raise jwt.PyJWKClientConnectionError("identity provider unavailable")
            raise jwt.PyJWKClientError("unknown signing key")
        self.fetched_at, self.failed = time.monotonic(), True
        data = super().fetch_data()
        self.failed = False
        return data
```

Why this works, against PyJWT 2.13 `jwks_client.py` (read in `.venv`):
`get_signing_key_from_jwt` calls `self.get_signing_key(kid)`; `get_signing_key` calls
`get_signing_keys()` (cache, `lifespan=300`) and, on no match, `get_signing_keys(refresh=True)`;
both reach `fetch_data()` only when they need the network. `fetch_data` puts the set in the cache
only on success. So:

- first use, and the 300 s cache expiry: last fetch is ≥ 30 s old, so one fetch happens;
- an unknown `kid` (random, or a real rotation) within 30 s of the last fetch: no fetch,
  `PyJWKClientError("unknown signing key")` → 401; after 30 s, one refetch, as PyJWT does today;
- a failed fetch (`PyJWKClientConnectionError`, or a `ValueError` from a non-JSON body) leaves
  `failed = True`; for 30 s every lookup raises `PyJWKClientConnectionError` without fetching →
  503 (below);
- the lock covers `get_signing_key`, so check-then-set in `fetch_data` can't race and concurrent
  lookups at cache expiry wait for one fetch and then read the cache.
  `get_signing_key` is a plain method here (`cache_keys=False`, the default), so the override is
  the one `get_signing_key_from_jwt` calls.

`_JWKS` does not set `cache_keys`, `lifespan` or headers; defaults stay as today.

**security-r0-1: discovery.** `_oidc()` holds a module lock `_OIDC_LOCK = threading.Lock()` for its
whole body and backs off after a failure:

```python
def _oidc() -> dict:
    """The provider's discovery document, fetched on first use (an outage doesn't stop the app starting).
    A failed fetch is retried at most once per PROVIDER_RETRY_SECONDS; meanwhile callers get RuntimeError."""
    with _OIDC_LOCK:   # one discovery at a time; the others wait for its answer
        if AUTH["oidc"] is None:
            failed = AUTH["oidc_failed_at"]
            if failed is not None and time.monotonic() - failed < PROVIDER_RETRY_SECONDS:
                raise RuntimeError("identity provider unavailable")
            try:
                doc = _get_json(AUTH["issuer"] + ".well-known/openid-configuration")
                if doc.get("issuer") != AUTH["issuer"] or not all(
                        k in doc for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
                    raise RuntimeError("identity provider misconfigured")
            except Exception:
                AUTH["oidc_failed_at"] = time.monotonic()
                raise
            AUTH["jwks"] = _JWKS(doc["jwks_uri"])
            AUTH["oidc"] = doc
        return AUTH["oidc"]
```

Callers (`login`, `callback`, `logout`, `_verify`) keep their existing `except` tuples. Note the
`except Exception` here only records the time and re-raises, it swallows nothing.

**`_verify(token, nonce)`** keeps its signature and stays the one complete check (signature,
`iss`, `aud`, `exp`/`iat`/`sub`, nonce, then `_require_group`), so no caller can skip the group.
Only the exception mapping changes:

```python
    try:
        _oidc()
        key = AUTH["jwks"].get_signing_key_from_jwt(token).key
        claims = jwt.decode(...)                     # unchanged
    except jwt.PyJWKClientConnectionError:           # before PyJWTError: it is a subclass
        raise ProviderUnavailable("identity provider unavailable") from None
    except jwt.PyJWTError as e:
        raise PermissionError(str(e)) from None
    except (OSError, ValueError, RuntimeError, KeyError):   # discovery failed, was malformed, or is backing off
        raise ProviderUnavailable("identity provider unavailable") from None
```

`_require_group` raises `NotInGroup("not in the required group")` instead of `PermissionError`.

**ux-r0-4.** `challenge()`:

```python
def challenge() -> dict:
    """Headers for a 401: the Basic login prompt under password, a Bearer challenge (RFC 6750) under authentik."""
    if AUTH["mode"] == "password":
        return {"WWW-Authenticate": 'Basic realm="uccc-genomics"'}
    if AUTH["mode"] == "authentik":
        return {"WWW-Authenticate": 'Bearer realm="uccc-genomics"'}
    return {}
```

`app.user()` (the FastAPI dependency) already passes `authen.challenge()`, so it follows.

**ux-r0-3 / ux-r1-1: the pages.** One shared head for both fixed pages:

```python
_HEAD = ('<!doctype html><html lang="en"><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1">'
         '<title>UCCC genomics</title><h1>UCCC genomics</h1>')
_PAGE = _HEAD + '<p>{}</p><p><a href="/auth/login">Sign in</a></p>'
```

`signin_page()` starts with `_HEAD` instead of its own `<!doctype …><title>…</title>` prefix; the
rest of its body (`Signing in&hellip;`, the link, the script) is unchanged.

A helper builds the help sentence from configuration only, escaped:

```python
def _access_help() -> str:
    return ACCESS_HELP.format(group=html.escape(AUTH["group"]))
```

`login`: the 502 page text becomes `UNREACHABLE` (was "The identity provider is not reachable.").

**code-r0-1 and ux-r0-3/ux-r1-1: `callback`.** Changes only in the steps named:

1. `error` in the query → `_refuse(403, "Sign-in was refused. " + _access_help())`.
2. State check compares bytes:
   `hmac.compare_digest(q["state"].encode(), login_claims["state"].encode())`. Non-ASCII `state`
   now reaches the existing 400 "Sign-in expired or was started elsewhere; try again." and clears
   `uccc_login`.
3. Token exchange failure: unchanged (502 "Sign-in failed at the identity provider.").
4. `_verify(id_token, login_claims["nonce"])`:
   - `NotInGroup` → `_refuse(403, "You don't have access to this app. " + _access_help())`;
   - `ProviderUnavailable` → `_refuse(502, UNREACHABLE)`;
   - any other `PermissionError` (bad signature, `iss`, `aud`, expired, `iat` too far ahead,
     nonce) → `_refuse(403, "Sign-in failed; try again.")`.
   Catch them in that order (subclasses first).

`_refuse` is unchanged (formats `_PAGE`, clears `uccc_login`). Page text comes only from the
constants above and `AUTH["group"]` (escaped), never from request values.

### `app.py`

`RequireUser.__call__`, in the `except PermissionError as e:` branch, before the existing
sign-in-page / 401 choice:

```python
            if isinstance(e, authen.ProviderUnavailable):   # a Bearer token we couldn't check: not the caller's fault
                response = JSONResponse({"detail": str(e)}, status_code=503,
                                        headers={"Retry-After": str(authen.PROVIDER_RETRY_SECONDS)})
            elif login and ...:   # existing sign-in page branch, unchanged
            else:                 # existing 401 JSON branch, unchanged (now with the Bearer challenge)
```

Only the Bearer path and the callback can raise `ProviderUnavailable`; a session cookie is checked
locally and never reaches the provider. The class docstring adds: "a Bearer token that can't be
checked because the provider is unreachable gets 503."

### `web/src/transport.ts` (security-r0-3)

A named check, matching `authen._safe_next` (leading `/`, not `//`, no `\`):

```ts
/** A same-site path: starts with "/", not "//" (protocol-relative) and no "\" (browsers read "/\" as "//"). */
export function sameSitePath(p: unknown): p is string {
  return typeof p === "string" && p.startsWith("/") && !p.startsWith("//") && !p.includes("\\");
}
```

In `requester`, the 401 line becomes
`if (res.status === 401 && sameSitePath(login)) signIn(login);`.

### `web/src/App.tsx` (ux-r0-5)

- `Who`: `<span className="who"><span className="sr-only">Signed in as </span>{me.email}</span>`
  (`.sr-only` already exists in `styles.css`).
- The sign-out handler: `account.signOut().catch((e) => setEditError({at: "builder", message:
  \`Sign-out failed: ${describeError(e)}\`}))`, the same pattern as the share-link error, shown in
  the existing builder `role="alert"` paragraph.

### `README.md`

In § Campus sign-in (Authentik), replace "`/api/*` and `/mcp` answer 401 without a login;" with:
"`/api/*` and `/mcp` answer 401 without a login (with `WWW-Authenticate: Bearer
realm="uccc-genomics"`), or 503 with `Retry-After` when a Bearer token can't be checked because
Authentik is unreachable. The app fetches Authentik's discovery document and key set at most once
per 30 s, so a new signing key is accepted within 30 s of the last fetch at the latest after one
retry window;". After the sentence ending "a non-member is refused at Authentik or on the
callback.", add: "A refusal page names the group (`AUTHENTIK_GROUP`) and says to ask the UCCC
genomics team; a failure that is not about the group says 'Sign-in failed; try again.'"

## Acceptance criteria

- [ ] `GET /auth/callback?code=<code>&state=é` with a valid `uccc_login` → 400, `uccc_login`
      cleared, no `uccc_session`.
- [ ] After one valid Bearer request (one JWKS fetch), two Bearer requests whose tokens carry
      random `kid`s → 401 each and no further JWKS fetch. After `fetched_at` is aged by
      `PROVIDER_RETRY_SECONDS`, the next random-`kid` request makes exactly one fetch and the one
      after it none.
- [ ] A rotated key (`kid` `k2`) within 30 s of the last fetch → 401 without a fetch; after aging,
      accepted with exactly one extra fetch.
- [ ] Discovery down: two Bearer requests on `/mcp` → 503 each with `Retry-After: 30`, and exactly
      one discovery request reached the issuer. After the issuer is back and `oidc_failed_at` is
      aged, the next request succeeds.
- [ ] JWKS endpoint down (discovery up): a Bearer request → 503; a second within 30 s → 503
      without another JWKS request.
- [ ] `GET /auth/login` with the issuer down → 502 with the `UNREACHABLE` text; the issuer back
      and `oidc_failed_at` aged → 302.
- [ ] Under `authentik`, every non-static `GATED` 401 JSON answer has
      `WWW-Authenticate: Bearer realm="uccc-genomics"`. Under `password`, still `Basic`; under
      `none`/`access`, no change.
- [ ] Callback with `groups` missing, another group, or a string → 403 whose text contains
      "You don't have access to this app." and "uccc-genomics-dashboard group". Wrong `iss`, `aud`,
      expired, other key, HS256, missing or wrong nonce, `iat` 5 min ahead → 403 "Sign-in failed;
      try again." without "don't have access". JWKS down at callback → 502.
- [ ] `error` in the callback query → 403 containing "Sign-in was refused." and the group sentence;
      the `error_description` value is not in the page.
- [ ] With `AUTHENTIK_GROUP` set to a value containing `<b>&`, the refusal page contains
      `&lt;b&gt;&amp;` and not `<b>&`.
- [ ] `_PAGE` refusal pages and `signin_page()` contain `<html lang="en">`, the viewport meta and
      `<h1>`.
- [ ] Discover: a 401 with `login` `//evil.example` or `/\evil.example` does not call `signIn`;
      `/auth/login` still does. `Who` renders `Signed in as </span>a@example.edu`.
- [ ] `uv run pytest -q` and `cd web && bun install --frozen-lockfile && bun run typecheck && bun
      test` pass. Dashboard check n/a (nothing under `dashboard/`).

## Test plan

No network, no `$DATA`, no PHI file, no real de-id file: the tests reuse `tests/test_authen.py`'s
`FakeIssuer` (in place of `urllib.request.urlopen`, which both `_get_json` and
`PyJWKClient.fetch_data` call) and the synthetic mart from `tests/test_app.py`.

`tests/test_authen.py`:

- `FakeIssuer`: add `self.discovery_fetches = 0` and `self.jwks_down = False`. In `urlopen`, count
  a discovery request **before** the `down` check (so failed attempts count); for the JWKS URL,
  count `jwks_fetches` before raising `URLError("down")` when `jwks_down` (so failed attempts
  count too).
- A helper `age(seconds=authen.PROVIDER_RETRY_SECONDS)` in the test module subtracts from
  `authen.AUTH["jwks"].fetched_at` (when set) and `authen.AUTH["oidc_failed_at"]` (when not
  `None`); the tests never sleep or patch `time`.
- A helper `random_kid_token(issuer)`:
  `jwt.encode(issuer.claims(), KEYS["k1"], algorithm="RS256", headers={"kid": secrets.token_hex(8)})`.
- `test_callback_refuses_a_flow_that_did_not_start_here`: add `"non-ascii-state"` (sets
  `params["state"] = "é"`), expecting 400 and `never_signed_in`; also assert
  `"uccc_login=" in r.headers["set-cookie"]` for every case.
- `test_callback_refuses_bad_id_tokens`: keep the 403; split the ids into group cases
  (`no-groups`, `other-group`, `groups-string`), asserting "You don't have access to this app." and
  `GROUP + " group"` in `r.text`, and the rest, asserting "Sign-in failed; try again." and not
  "don't have access". `test_callback_refuses_an_iat_far_in_the_future` asserts the
  "Sign-in failed" text too.
- New `test_callback_when_the_jwks_is_down_is_502`: `issuer.jwks_down = True`, run a sign-in → 502,
  `never_signed_in`.
- `test_callback_refuses_an_error_from_the_provider`: also assert "Sign-in was refused." and the
  group sentence.
- New `test_refusal_page_escapes_the_group`: `monkeypatch.setenv("AUTHENTIK_GROUP", "g<b>&")`,
  build the client with `make()`, GET `/auth/callback?error=x` after `begin` → contains
  `g&lt;b&gt;&amp;`, not `g<b>&`.
- New `test_pages_have_lang_viewport_and_heading`: the 400 callback page and the static sign-in
  page (`GET /`) both contain `<html lang="en">`, `name="viewport"` and `<h1>`.
- `test_login_when_the_issuer_is_down_is_502`: after `issuer.down = False`, assert
  `c.get("/auth/login").status_code == 502` (backing off), then `age()` and assert 302; assert
  `issuer.discovery_fetches == 2`. The docstring comment changes from "the failure was not cached"
  to "retried after PROVIDER_RETRY_SECONDS".
- `test_signed_out_gets_401_or_a_redirect`: in the 401 branch also assert
  `r.headers["www-authenticate"] == 'Bearer realm="uccc-genomics"'`.
- `test_rotated_signing_key_is_accepted_after_one_refetch`: after `issuer.rotate()`, assert the
  `k2` token → 401 and `jwks_fetches == 1`; `age()`; assert 200 and `jwks_fetches == 2`.
- New `test_random_kids_cause_at_most_one_fetch`: one valid `mcp_post` (`jwks_fetches == 1`); two
  `random_kid_token` posts → 401, still 1; `age()`; two more → 401, `jwks_fetches == 2`.
- New `test_bearer_when_discovery_is_down_is_503`: `issuer.down = True`; two `mcp_post`s → 503
  with `Retry-After == "30"`; `issuer.discovery_fetches == 1`; `issuer.down = False`; `age()`;
  `mcp_post` → 200.
- New `test_bearer_when_the_jwks_is_down_is_503`: `issuer.jwks_down = True`; two `mcp_post`s →
  503; `issuer.jwks_fetches == 1`.
- `test_logout_without_a_session_or_issuer`: unchanged; still `{"url": "/"}`.

`tests/test_app.py`: no change; `test_refused_without_login` already pins `Basic` under `password`.

`web/src/transport.test.ts`: in "a 401 without one, or with an off-site one, does not", add
`{detail: "x", login: "//evil.example"}` and `{detail: "x", login: "/\\evil.example"}`.

`web/src/app.test.tsx`: in `Who`, assert `html(true)` contains
`<span class="sr-only">Signed in as </span>a@example.edu`.

Commands: `uv run pytest -q`; `cd web && bun install --frozen-lockfile && bun run typecheck && bun
test`. Dashboard: n/a.

## Risks

- **Seam (`authen`, label `seam`).** `_require_group` now raises a subclass and `_verify` maps
  failures into two subclasses. Every existing `except PermissionError` still refuses, so the
  change can't let anyone in; the parametrized callback and Bearer tests pin each refusal.
- **Key rotation delay.** A token signed with a new key within 30 s of the last JWKS fetch is
  refused until the window passes (then one refetch). Authentik publishes keys before use in
  normal rotation, and the 300 s cache expiry refetches anyway; the worst case is a 401 for up to
  30 s, which a client retries.
- **Outage stickiness.** After a failed discovery or JWKS fetch, sign-in pages say "not reachable"
  and Bearer calls get 503 for up to 30 s after Authentik recovers. Existing session cookies are
  unaffected (checked locally).
- **Lock waits.** During a slow fetch (up to the 10 s timeout) other Bearer lookups and
  discovery callers wait on the lock in the threadpool, as they would have each been fetching
  before. Afterwards they are answered without network for 30 s, so a flood of unauthenticated
  Bearer requests costs at most one fetch per 30 s instead of one per request.
- **503 classification.** A `ValueError`/`OSError` inside `_verify` is read as a provider
  problem; a malformed token raises `jwt.DecodeError` (a `PyJWTError`) first, so it stays 401.
- **UI error wording.** "Sign-out failed: network error" appears in the builder's alert area,
  which the next edit clears. The handler wiring is not unit-tested (no DOM test runner in
  `web/`); `Who` and the transport check are.
