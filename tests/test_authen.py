"""The `authentik` auth backend: sign-in routes, session cookie, Bearer tokens (docs/specs/95-*.md).

No network: a FakeIssuer replaces urllib.request.urlopen (discovery, JWKS and the token endpoint) and
signs tokens with a throwaway RSA key. Runs on the synthetic #34 mart; never $DATA or a real provider.
"""
import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from test_app import GATED, MCP_HEADERS, ids, mart_file  # noqa: F401  (fixtures)
from uccc_genomics_mcp import app, authen

ISS = "https://id.example.test/application/o/uccc-genomics/"
CLIENT_ID, CLIENT_SECRET, GROUP = "uccc-genomics", "synthetic-client-secret", "uccc-genomics-dashboard"
SESSION_SECRET = "s" * 48
DROP = object()   # an override value that removes the claim
KEYS = {kid: rsa.generate_private_key(public_exponent=65537, key_size=2048) for kid in ("k1", "k2", "other")}


class FakeIssuer:
    def __init__(self):
        self.kid, self.alg, self.sign_with, self.override = "k1", "RS256", None, {}
        self.jwks_fetches, self.codes, self.last_form = 0, {}, None
        self.token_fails = self.down = False

    # claims -------------------------------------------------------------------------------------
    def claims(self, **override):
        now = int(time.time())
        c = {"iss": ISS, "aud": CLIENT_ID, "sub": "synthetic-sub-1", "email": "member@example.edu",
             "groups": [GROUP], "iat": now, "exp": now + 300} | override
        return {k: v for k, v in c.items() if v is not DROP}

    def token(self, key=None, alg=None, **override):
        """A token signed like the provider's (override: claim changes; DROP removes one)."""
        alg = alg or self.alg
        key = ("x" * 48 if alg == "HS256" else KEYS[key or self.sign_with or self.kid])
        return jwt.encode(self.claims(**override), key, algorithm=alg, headers={"kid": self.kid})

    def rotate(self):
        self.kid = "k2"

    # the three endpoints, called in place of urllib.request.urlopen ------------------------------
    def urlopen(self, req, timeout=None, context=None):
        if self.down:
            raise urllib.error.URLError("down")
        url = req.full_url
        if url == ISS + ".well-known/openid-configuration":
            body = {"issuer": ISS, "authorization_endpoint": ISS + "authorize/", "token_endpoint": ISS + "token/",
                    "jwks_uri": ISS + "jwks/", "end_session_endpoint": ISS + "end-session/"}
        elif url == ISS + "jwks/":
            self.jwks_fetches += 1
            body = {"keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(KEYS[k].public_key(), as_dict=True),
                              "kid": k, "alg": "RS256", "use": "sig"} for k in ("k1", self.kid)]}
        elif url == ISS + "token/":
            body = self.exchange(dict(urllib.parse.parse_qsl(req.data.decode())))
        else:
            raise AssertionError(f"unexpected request to {url}")
        return io.BytesIO(json.dumps(body).encode())

    def authorize(self, location: str) -> str:
        """The user approves at the provider: remember the request, hand back a one-time code."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))
        code = f"code-{len(self.codes)}"
        self.codes[code] = q
        return code

    def exchange(self, form):
        self.last_form = form
        asked = self.codes.pop(form.get("code"), None)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        if (self.token_fails or asked is None or asked["code_challenge"] != challenge
                or form["redirect_uri"] != asked["redirect_uri"] or form["client_id"] != CLIENT_ID
                or form["client_secret"] != CLIENT_SECRET or form["grant_type"] != "authorization_code"):
            raise urllib.error.HTTPError(ISS + "token/", 400, "bad request", {}, io.BytesIO(b"{}"))
        claims = {"nonce": asked["nonce"]} | self.override
        return {"id_token": self.token(**claims), "access_token": self.token(**self.override), "token_type": "Bearer"}


@pytest.fixture
def issuer(ids, monkeypatch):   # noqa: F811
    fake = FakeIssuer()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in {"AUTHENTIK_ISSUER": ISS, "AUTHENTIK_CLIENT_ID": CLIENT_ID, "AUTHENTIK_CLIENT_SECRET": CLIENT_SECRET,
                 "APP_BASE_URL": "http://testserver", "SESSION_SECRET": SESSION_SECRET}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AUTHENTIK_GROUP", raising=False)
    return fake


@pytest.fixture
def make(issuer, tmp_path, monkeypatch):
    """make(base) -> a client for the app configured for authentik at APP_BASE_URL=base."""
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<p>site</p>")
    with ExitStack() as stack:
        def factory(base="http://testserver"):
            monkeypatch.setenv("APP_BASE_URL", base)
            authen.configure("authentik")
            return stack.enter_context(TestClient(app.app(str(tmp_path / "static")), base_url=base,
                                                  follow_redirects=False))
        yield factory


@pytest.fixture
def c(make):
    return make()


def begin(c, issuer, next=None):
    """GET /auth/login and approve at the provider: (state, code)."""
    r = c.get("/auth/login", params={"next": next} if next is not None else {})
    assert r.status_code == 302
    loc = r.headers["location"]
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))["state"], issuer.authorize(loc)


def sign_in(c, issuer, next=None, **override):
    issuer.override = override
    state, code = begin(c, issuer, next)
    return c.get("/auth/callback", params={"code": code, "state": state})


def me(c):
    return c.get("/api/me")


# --- configure -----------------------------------------------------------------------------------

REQUIRED = ["AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_CLIENT_SECRET", "APP_BASE_URL", "SESSION_SECRET"]


@pytest.mark.parametrize("missing", [[v] for v in REQUIRED] + [["AUTHENTIK_CLIENT_SECRET", "SESSION_SECRET"]])
def test_configure_names_every_missing_variable(issuer, monkeypatch, missing):
    for name in missing:
        monkeypatch.delenv(name)
    with pytest.raises(SystemExit) as e:
        authen.configure("authentik")
    assert str(e.value).startswith("--auth authentik needs ") and all(n in str(e.value) for n in missing)


@pytest.mark.parametrize("name, value, named", [
    ("SESSION_SECRET", "short", "SESSION_SECRET"),
    ("AUTHENTIK_ISSUER", "https://id.example.test/application/o/uccc-genomics", "AUTHENTIK_ISSUER"),
    ("APP_BASE_URL", "app.example.test", "APP_BASE_URL")])
def test_configure_rejects_invalid_values(issuer, monkeypatch, name, value, named):
    monkeypatch.setenv(name, value)
    monkeypatch.setenv("AUTHENTIK_CLIENT_ID", "")   # and several problems are all named
    with pytest.raises(SystemExit) as e:
        authen.configure("authentik")
    assert named in str(e.value) and "AUTHENTIK_CLIENT_ID" in str(e.value)
    assert value not in str(e.value)


def test_configure_does_no_network(issuer, monkeypatch):
    issuer.down = True
    authen.configure("authentik")
    assert authen.AUTH["group"] == GROUP and authen.AUTH["oidc"] is None


# --- login and callback --------------------------------------------------------------------------

def test_login_redirects_to_the_issuer(c, issuer):
    r = c.get("/auth/login")
    assert r.status_code == 302
    url = urllib.parse.urlparse(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == ISS + "authorize/"
    q = dict(urllib.parse.parse_qsl(url.query))
    assert (q["response_type"], q["client_id"], q["redirect_uri"], q["code_challenge_method"]) == (
        "code", CLIENT_ID, "http://testserver/auth/callback", "S256")
    assert {"openid", "profile"} <= set(q["scope"].split()) and q["state"] and q["nonce"] and q["code_challenge"]
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("uccc_login=") and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/auth" in cookie and "secure" not in cookie


def test_login_when_the_issuer_is_down_is_502(c, issuer):
    issuer.down = True
    assert c.get("/auth/login").status_code == 502
    issuer.down = False
    assert c.get("/auth/login").status_code == 302   # the failure was not cached


def test_member_signs_in(c, issuer, capsys):
    r = sign_in(c, issuer)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("uccc_session="))
    low = cookie.lower()
    assert "httponly" in low and "samesite=lax" in low and "max-age=28800" in low and "secure" not in low
    s = jwt.decode(c.cookies["uccc_session"], SESSION_SECRET, algorithms=["HS256"], audience="uccc-genomics-session")
    assert set(s) == {"aud", "sub", "email", "iat", "exp"} and s["exp"] - s["iat"] == 28800
    assert (s["sub"], s["email"]) == ("synthetic-sub-1", "member@example.edu")
    assert me(c).json() == {"sub": "synthetic-sub-1", "email": "member@example.edu", "sign_out": True}
    capsys.readouterr()
    assert c.post("/api/cohort", json={}).status_code == 200
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["sub"], line["email"]) == ("synthetic-sub-1", "member@example.edu")


def test_token_request_carries_pkce_redirect_and_client(c, issuer):
    state, code = begin(c, issuer)
    assert c.get("/auth/callback", params={"code": code, "state": state}).status_code == 303
    f = issuer.last_form   # exchange() already refused a verifier that doesn't match the challenge
    assert (f["grant_type"], f["redirect_uri"], f["client_id"], f["client_secret"]) == (
        "authorization_code", "http://testserver/auth/callback", CLIENT_ID, CLIENT_SECRET)


def test_secure_cookie_only_over_https(make, issuer):
    c = make("https://app.example.test")
    assert "secure" in c.get("/auth/login").headers["set-cookie"].lower()
    r = sign_in(c, issuer)
    assert r.status_code == 303 and "secure" in next(h for h in r.headers.get_list("set-cookie")
                                                    if h.startswith("uccc_session=")).lower()


def test_display_falls_back_to_username_then_sub(c, issuer):
    assert sign_in(c, issuer, email=DROP, preferred_username="0000-0001-0000-0000").status_code == 303
    assert me(c).json()["email"] == "0000-0001-0000-0000"
    c.cookies.clear()
    assert sign_in(c, issuer, email=DROP).status_code == 303
    assert me(c).json()["email"] == "synthetic-sub-1"


def never_signed_in(c, r):
    assert not any(h.startswith("uccc_session=") for h in r.headers.get_list("set-cookie"))
    assert "uccc_session" not in c.cookies and me(c).status_code == 401


@pytest.mark.parametrize("tweak", [
    lambda i: i.override.update(iss="https://evil.example.test/"),
    lambda i: i.override.update(aud="other-client"),
    lambda i: i.override.update(iat=int(time.time()) - 900, exp=int(time.time()) - 600),
    lambda i: setattr(i, "sign_with", "other"),   # kid k1 in the header, signed by another key
    lambda i: setattr(i, "alg", "HS256"),
    lambda i: i.override.update(groups=DROP),
    lambda i: i.override.update(groups=["some-other-group"]),
    lambda i: i.override.update(groups=GROUP),   # not a list
    lambda i: i.override.update(nonce=DROP),
    lambda i: i.override.update(nonce="wrong"),
], ids=["iss", "aud", "expired", "other-key", "hs256", "no-groups", "other-group", "groups-string",
        "no-nonce", "wrong-nonce"])
def test_callback_refuses_bad_id_tokens(c, issuer, tweak):
    tweak(issuer)
    state, code = begin(c, issuer)
    r = c.get("/auth/callback", params={"code": code, "state": state})
    assert r.status_code == 403 and "uccc_login=" in r.headers["set-cookie"]
    never_signed_in(c, r)


def test_callback_tolerates_provider_clock_skew(c, issuer):
    now = int(time.time())
    assert sign_in(c, issuer, iat=now + 5, exp=now + 305).status_code == 303


def test_callback_refuses_an_iat_far_in_the_future(c, issuer):
    now = int(time.time())
    issuer.override.update(iat=now + 300, exp=now + 600)
    state, code = begin(c, issuer)
    assert c.get("/auth/callback", params={"code": code, "state": state}).status_code == 403


@pytest.mark.parametrize("what", ["bad-state", "no-state", "no-code", "no-login-cookie"])
def test_callback_refuses_a_flow_that_did_not_start_here(c, issuer, what):
    state, code = begin(c, issuer)
    params = {"code": code, "state": state}
    if what == "bad-state":
        params["state"] = "x" * len(state)
    elif what == "no-state":
        del params["state"]
    elif what == "no-code":
        del params["code"]
    else:
        c.cookies.delete("uccc_login", path="/auth")
    r = c.get("/auth/callback", params=params)
    assert r.status_code == 400
    never_signed_in(c, r)


def test_callback_refuses_an_error_from_the_provider(c, issuer):
    begin(c, issuer)
    r = c.get("/auth/callback", params={"error": "access_denied", "error_description": "<script>x</script>"})
    assert r.status_code == 403 and "script" not in r.text
    never_signed_in(c, r)


def test_callback_when_the_token_endpoint_fails_is_502(c, issuer):
    issuer.token_fails = True
    state, code = begin(c, issuer)
    r = c.get("/auth/callback", params={"code": code, "state": state})
    assert r.status_code == 502
    never_signed_in(c, r)


@pytest.mark.parametrize("next, landing", [
    ("//evil.example", "/"), ("https://evil.example", "/"), ("/auth/logout", "/"), ("/\\evil.example", "/"),
    ("/x\r\ny", "/"), ("/x?y=1#d=abc", "/x?y=1#d=abc"), (None, "/")])
def test_next_is_same_site_only(c, issuer, next, landing):
    r = sign_in(c, issuer, next=next)
    assert r.status_code == 303 and r.headers["location"] == landing


# --- the session cookie --------------------------------------------------------------------------

def test_bad_session_cookies_are_refused(c, issuer):
    now = int(time.time())
    aud = "uccc-genomics-session"
    good = {"aud": aud, "sub": "s", "email": "e", "iat": now, "exp": now + 60}
    r = c.get("/auth/login")
    login_cookie = c.cookies["uccc_login"]
    for value in (jwt.encode(good, "o" * 48, algorithm="HS256"),
                  jwt.encode(good | {"iat": now - 100, "exp": now - 50}, SESSION_SECRET, algorithm="HS256"),
                  login_cookie, "garbage"):
        c.cookies.clear()
        c.cookies.set("uccc_session", value)
        r = me(c)
        assert r.status_code == 401 and r.json()["login"] == "/auth/login"
    c.cookies.clear()
    c.cookies.set("uccc_session", jwt.encode(good, SESSION_SECRET, algorithm="HS256"))
    assert me(c).json()["sub"] == "s"


def test_session_cookie_is_not_a_login_cookie(c, issuer):
    sign_in(c, issuer)
    session = c.cookies["uccc_session"]
    c.cookies.clear()
    c.cookies.set("uccc_login", session, path="/auth")
    state, code = begin(c, issuer)   # replaces the cookie with a real login cookie
    c.cookies.clear()
    c.cookies.set("uccc_login", session, path="/auth")
    assert c.get("/auth/callback", params={"code": code, "state": state}).status_code == 400


# --- gating --------------------------------------------------------------------------------------

STATIC = [("GET", "/"), ("GET", "/index.html"), ("GET", "/no/such/path")]


@pytest.mark.parametrize("method, path", GATED)
def test_signed_out_gets_401_or_a_redirect(c, method, path):
    r = c.request(method, path, headers={"accept": "application/json"})
    if (method, path) in STATIC:
        assert_signin_page(r)
    else:
        assert r.status_code == 401 and r.json()["login"] == "/auth/login" and "location" not in r.headers


def assert_signin_page(r):
    """The page that carries path, query and #fragment to /auth/login (a server redirect would drop the fragment)."""
    assert r.status_code == 401 and "location" not in r.headers and "content-security-policy" not in r.headers
    assert r.headers["content-type"].startswith("text/html")
    assert "location.replace(\"/auth/login?next=\" + encodeURIComponent(location.pathname + location.search + location.hash))" in r.text
    assert '<a href="/auth/login">Sign in</a>' in r.text


def test_signed_out_share_link_survives_sign_in(c, issuer):
    """The page's script sends /x?q=1#d=abc to /auth/login?next=<that>; the callback lands back on it."""
    assert_signin_page(c.get("/no/such/path?q=1&r=a b"))
    next = "/x?q=1#d=abc"
    r = sign_in(c, issuer, next=next)
    assert r.status_code == 303 and r.headers["location"] == next


@pytest.mark.parametrize("method, path", GATED)
def test_session_cookie_opens_every_route(c, issuer, method, path):
    assert sign_in(c, issuer).status_code == 303
    r = c.request(method, path, headers={"accept": "application/json"})
    assert r.status_code not in (401, 302)


def test_open_paths(c, issuer):
    assert c.get("/api/health").status_code == 200
    assert c.get("/auth/login").status_code == 302
    assert c.get("/auth/callback").status_code == 400
    assert c.post("/auth/logout").status_code == 200


# --- Bearer tokens -------------------------------------------------------------------------------

BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "count", "arguments": {"definition": {}}}}


def mcp_post(c, token):
    return c.post("/mcp", json=BODY, headers=MCP_HEADERS | {"authorization": f"Bearer {token}"})


def test_bearer_token_runs_count(c, issuer):
    r = mcp_post(c, issuer.token())
    assert r.status_code == 200 and not r.json()["result"]["isError"]
    assert c.get("/api/me", headers={"authorization": f"bearer {issuer.token()}"}).json()["sub"] == "synthetic-sub-1"


@pytest.mark.parametrize("override", [
    {"aud": "other"}, {"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}, {"groups": DROP},
    {"groups": ["other"]}, {"iss": "https://evil.example.test/"}], ids=["aud", "expired", "no-group", "other-group", "iss"])
def test_bad_bearer_tokens_are_401(c, issuer, override):
    assert mcp_post(c, issuer.token(**override)).status_code == 401


def test_bad_bearer_does_not_fall_back_to_the_cookie(c, issuer):
    sign_in(c, issuer)
    assert me(c).status_code == 200
    assert c.get("/api/me", headers={"authorization": "Bearer garbage"}).status_code == 401


def test_rotated_signing_key_is_accepted_after_one_refetch(c, issuer):
    assert mcp_post(c, issuer.token()).status_code == 200
    assert issuer.jwks_fetches == 1
    issuer.rotate()
    assert mcp_post(c, issuer.token()).status_code == 200
    assert issuer.jwks_fetches == 2


# --- logout --------------------------------------------------------------------------------------

def test_logout_clears_the_cookie_and_returns_the_end_session_url(c, issuer):
    sign_in(c, issuer)
    assert me(c).status_code == 200
    r = c.post("/auth/logout")
    assert r.status_code == 200 and r.json() == {"url": ISS + "end-session/"}
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert me(c).status_code == 401


def test_logout_without_a_session_or_issuer(c, issuer):
    issuer.down = True
    r = c.post("/auth/logout")
    assert r.status_code == 200 and r.json() == {"url": "/"}
