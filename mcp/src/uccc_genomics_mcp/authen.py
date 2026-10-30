"""Who is calling: `user(request) -> User`, or PermissionError. The backend is chosen once by `configure()`.

- `none`: local dev, everyone is dev@localhost.
- `password`: one local account over HTTP Basic (APP_USER, APP_PASSWORD_HASH in .env). A development
  stand-in; it sends the password on every request, so use it on localhost or behind TLS only.
- `access`: a Cloudflare Access JWT, what production runs today.
- `authentik`: campus sign-in through the central Authentik (docs/specs/95-*.md): authorization code
  flow with PKCE, a signed app cookie for 8 hours, or a Bearer access token for /mcp. Authorizes on the
  `groups` claim only. The /auth/login, /auth/callback and /auth/logout endpoints live here; app.py
  registers them.

    uv run python -m uccc_genomics_mcp.authen   # prompts for a password, prints APP_PASSWORD_HASH
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

import jwt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

MODES = ("access", "password", "none", "authentik")
SESSION_COOKIE = "uccc_session"      # signed-in user; HS256 JWT, aud SESSION_AUD
LOGIN_COOKIE = "uccc_login"          # one sign-in in flight; HS256 JWT, aud LOGIN_AUD, Path=/auth
SESSION_AUD = "uccc-genomics-session"
LOGIN_AUD = "uccc-genomics-login"
SESSION_HOURS = 8
LOGIN_SECONDS = 600
OPEN_PATHS = ("/auth/login", "/auth/callback", "/auth/logout")   # open under authentik only
DEFAULT_GROUP = "uccc-genomics-dashboard"


@dataclass(frozen=True)
class User:
    sub: str     # stable key: owner of saved cohorts and snapshots, rate-limit key
    email: str   # display label and audit log; may not be an email (ORCID sign-ins have none)


AUTH = {"mode": "none", "team": None, "aud": None, "jwks": None, "user": None, "hash": None,
        "issuer": None, "client_id": None, "client_secret": None, "base_url": None,
        "session_secret": None, "group": None, "oidc": None}


def configure(mode: str) -> None:
    """Set the backend from the environment; raises SystemExit naming what is missing."""
    if mode == "access":
        team, aud = os.environ.get("ACCESS_TEAM"), os.environ.get("ACCESS_AUD")
        if not (team and aud):
            raise SystemExit("--auth access needs ACCESS_TEAM and ACCESS_AUD (in .env)")
        AUTH.update(team=team, aud=aud, jwks=jwt.PyJWKClient(f"https://{team}.cloudflareaccess.com/cdn-cgi/access/certs"))
    elif mode == "password":
        name, h = os.environ.get("APP_USER"), os.environ.get("APP_PASSWORD_HASH")
        if not (name and h):
            raise SystemExit("--auth password needs APP_USER and APP_PASSWORD_HASH (in .env); "
                             "make the hash with `uv run python -m uccc_genomics_mcp.authen`")
        AUTH.update(user=name, hash=h)
    elif mode == "authentik":
        env = os.environ.get
        issuer, base = env("AUTHENTIK_ISSUER", ""), env("APP_BASE_URL", "")
        bad = [name for name in ("AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_CLIENT_SECRET",
                                 "APP_BASE_URL", "SESSION_SECRET") if not env(name)]
        if issuer and not issuer.endswith("/"):
            bad.append("AUTHENTIK_ISSUER (must end with /)")
        if base and not base.startswith(("http://", "https://")):
            bad.append("APP_BASE_URL (must start with http:// or https://)")
        if env("SESSION_SECRET") and len(env("SESSION_SECRET")) < 32:
            bad.append("SESSION_SECRET (at least 32 characters)")
        if bad:
            raise SystemExit(f"--auth authentik needs {', '.join(bad)} (in .env)")
        AUTH.update(issuer=issuer, client_id=env("AUTHENTIK_CLIENT_ID"), client_secret=env("AUTHENTIK_CLIENT_SECRET"),
                    base_url=base.rstrip("/"), session_secret=env("SESSION_SECRET"),
                    group=env("AUTHENTIK_GROUP") or DEFAULT_GROUP, oidc=None, jwks=None)
    AUTH["mode"] = mode


def challenge() -> dict:
    """Headers for a 401, so a browser shows its login prompt under the password backend."""
    return {"WWW-Authenticate": 'Basic realm="uccc-genomics"'} if AUTH["mode"] == "password" else {}


def login_path() -> str | None:
    """Where an unauthenticated browser navigation goes, or None when the backend has no sign-in page."""
    return "/auth/login" if AUTH["mode"] == "authentik" else None


def open_path(path: str) -> bool:
    """True for the sign-in endpoints, which need no login (only under authentik)."""
    return AUTH["mode"] == "authentik" and path in OPEN_PATHS


def user(request: Request) -> User:
    if AUTH["mode"] == "none":
        return User("dev@localhost", "dev@localhost")
    if AUTH["mode"] == "password":
        name = _basic(request.headers.get("authorization", ""))
        return User(name, name)
    if AUTH["mode"] == "authentik":
        return _authentik(request)
    email = _access(request)
    return User(email, email)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(password, salt).hex()}"


def _scrypt(password: str, salt: bytes) -> bytes:
    # ponytail: ~50 ms per request at these settings; fine for one local user, gone with Zitadel.
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def _basic(header: str) -> str:
    scheme, _, b64 = header.partition(" ")
    if scheme.lower() != "basic":
        raise PermissionError("missing credentials")
    try:
        name, _, password = base64.b64decode(b64, validate=True).decode().partition(":")
        _, salt, want = AUTH["hash"].split("$")
        ok = hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)), bytes.fromhex(want))
    except ValueError:  # bad base64/utf-8 from the client, or a malformed hash in .env
        raise PermissionError("bad credentials")
    if not (ok and hmac.compare_digest(name, AUTH["user"])):
        raise PermissionError("bad credentials")
    return name


def _access(request: Request) -> str:
    # Access sends the same JWT as a header and as the CF_Authorization cookie; the Worker forwards both.
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    if not token:
        raise PermissionError("missing Access token")
    try:
        key = AUTH["jwks"].get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUTH["aud"],
                            issuer=f"https://{AUTH['team']}.cloudflareaccess.com")
    except jwt.PyJWTError as e:
        raise PermissionError(str(e))
    return claims.get("email", "unknown")


# --- authentik -----------------------------------------------------------------------------------

def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _post_form(url: str, form: dict[str, str]) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers={
        "accept": "application/json", "content-type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _oidc() -> dict:
    """The provider's discovery document, fetched on first use (an outage doesn't stop the app starting)."""
    if AUTH["oidc"] is None:
        doc = _get_json(AUTH["issuer"] + ".well-known/openid-configuration")
        if doc.get("issuer") != AUTH["issuer"] or not all(
                k in doc for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
            raise RuntimeError("identity provider misconfigured")
        AUTH["jwks"] = jwt.PyJWKClient(doc["jwks_uri"], timeout=10)
        AUTH["oidc"] = doc
    return AUTH["oidc"]


def _require_group(claims: dict) -> None:
    groups = claims.get("groups")
    if not (isinstance(groups, list) and AUTH["group"] in groups):
        raise PermissionError("not in the required group")


def _verify(token: str, nonce: str | None) -> dict:
    """Check an ID or access token from the provider and the group; PermissionError otherwise."""
    try:
        _oidc()
        key = AUTH["jwks"].get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUTH["client_id"], issuer=AUTH["issuer"],
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError as e:
        raise PermissionError(str(e)) from None
    except (OSError, ValueError, RuntimeError, KeyError):   # discovery failed or was malformed
        raise PermissionError("identity provider unavailable") from None
    if nonce is not None:
        got = claims.get("nonce")
        if not (isinstance(got, str) and hmac.compare_digest(got, nonce)):
            raise PermissionError("bad nonce")
    _require_group(claims)
    return claims


def _display(claims: dict) -> str:
    # ORCID sign-ins carry no email. A label only: nothing verifies it and it never authorizes.
    return claims.get("email") or claims.get("preferred_username") or claims["sub"]


def _sign(claims: dict, aud: str, seconds: int) -> str:
    now = int(time.time())
    return jwt.encode({**claims, "aud": aud, "iat": now, "exp": now + seconds}, AUTH["session_secret"], algorithm="HS256")


def _unsign(token: str, aud: str) -> dict:
    return jwt.decode(token, AUTH["session_secret"], algorithms=["HS256"], audience=aud, options={"require": ["exp"]})


def _safe_next(raw: str | None) -> str:
    """A same-site path to return to after sign-in; anything else is `/`. Fragments are kept."""
    if (raw and raw.startswith("/") and not raw.startswith(("//", "/auth/")) and "\\" not in raw
            and not any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        return raw
    return "/"


def _cookie(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(name, value, max_age=max_age, path=path, httponly=True, samesite="lax",
                        secure=AUTH["base_url"].startswith("https://"))


def _authentik(request: Request) -> User:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        claims = _verify(token.strip(), None)   # a bad Bearer token is refused, never falls back to the cookie
        return User(claims["sub"], _display(claims))
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise PermissionError("not signed in")
    try:
        s = _unsign(cookie, SESSION_AUD)
    except jwt.PyJWTError:
        raise PermissionError("session expired") from None
    return User(s["sub"], s["email"])


_PAGE = ('<!doctype html><meta charset="utf-8"><title>UCCC genomics</title><p>{}</p>'
         '<p><a href="/auth/login">Sign in</a></p>')


def _refuse(status: int, message: str) -> Response:
    r = HTMLResponse(_PAGE.format(message), status_code=status)
    r.delete_cookie(LOGIN_COOKIE, path="/auth")
    return r


def login(request: Request) -> Response:
    """GET /auth/login: start the authorization code flow with PKCE, state and nonce."""
    try:
        oidc = _oidc()
    except (OSError, ValueError, RuntimeError, KeyError):
        return HTMLResponse(_PAGE.format("The identity provider is not reachable."), status_code=502)
    state, nonce, verifier = (secrets.token_urlsafe(n) for n in (32, 32, 48))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = RedirectResponse(oidc["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": AUTH["client_id"], "redirect_uri": AUTH["base_url"] + "/auth/callback",
        "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256"}), status_code=302)
    _cookie(r, LOGIN_COOKIE, _sign({"state": state, "nonce": nonce, "verifier": verifier,
                                    "next": _safe_next(request.query_params.get("next"))},
                                   LOGIN_AUD, LOGIN_SECONDS), LOGIN_SECONDS, "/auth")
    return r


def callback(request: Request) -> Response:
    """GET /auth/callback: exchange the code, check the ID token and the group, set the session cookie."""
    q = request.query_params
    if "error" in q:   # Authentik refuses non-members before it issues a code
        return _refuse(403, "Sign-in was refused.")
    try:
        login_claims = _unsign(request.cookies.get(LOGIN_COOKIE, ""), LOGIN_AUD)
    except jwt.PyJWTError:
        login_claims = None
    if (login_claims is None or not q.get("code") or not q.get("state")
            or not hmac.compare_digest(q["state"], login_claims["state"])):
        return _refuse(400, "Sign-in expired or was started elsewhere; try again.")
    try:
        answer = _post_form(_oidc()["token_endpoint"], {
            "grant_type": "authorization_code", "code": q["code"], "redirect_uri": AUTH["base_url"] + "/auth/callback",
            "code_verifier": login_claims["verifier"], "client_id": AUTH["client_id"],
            "client_secret": AUTH["client_secret"]})
        id_token = answer["id_token"]
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):   # URLError/HTTPError are OSErrors
        return _refuse(502, "Sign-in failed at the identity provider.")
    try:
        claims = _verify(id_token, login_claims["nonce"])
    except PermissionError:
        return _refuse(403, "You don't have access to this app.")
    r = RedirectResponse(login_claims["next"], status_code=303)
    _cookie(r, SESSION_COOKIE, _sign({"sub": claims["sub"], "email": _display(claims)}, SESSION_AUD,
                                     SESSION_HOURS * 3600), SESSION_HOURS * 3600, "/")
    r.delete_cookie(LOGIN_COOKIE, path="/auth")
    return r


def logout(request: Request) -> Response:
    """POST /auth/logout: clear the session cookie; the body's url is where the browser goes next."""
    try:
        url = _oidc().get("end_session_endpoint") or "/"
    except (OSError, ValueError, RuntimeError, KeyError):
        url = "/"
    r = JSONResponse({"url": url})
    r.delete_cookie(SESSION_COOKIE, path="/")
    return r


if __name__ == "__main__":
    pw = getpass.getpass("password: ")
    if pw != getpass.getpass("again: "):
        raise SystemExit("passwords differ")
    print(f"APP_PASSWORD_HASH={hash_password(pw)}")
