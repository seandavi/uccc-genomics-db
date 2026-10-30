"""Portal terms gate: acceptance at first login (docs/specs/131-*.md).

Synthetic #34 mart in a temp dir; the Postgres tests use the throwaway database of test_saved
(TEST_DATABASE_URL). Users are synthetic (a@x.edu). Never $DATA/raw, the PHI file, the real de-id file or the
real DATABASE_URL.
"""
import asyncio
import html
import uuid

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from test_app import GATED, MCP_HEADERS, ids, mart_file  # noqa: F401  (fixtures)
from test_authen import c, issuer, make, sign_in  # noqa: F401  (fixtures)
from test_saved import A, REPO, clean, pg_url, sql  # noqa: F401  (fixtures)
from uccc_genomics_mcp import app, authen, saved, terms

OPEN = {"/api/health", "/api/public/summary"}
HDR = {"x-test-user": A, "accept": "application/json"}
ACCEPT = {"version": terms.TERMS_VERSION}
COUNT_CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "count", "arguments": {"definition": {}}}}


def fake_user(request):
    try:
        h = request.headers["x-test-user"]
    except KeyError:
        raise PermissionError("no test user") from None
    return authen.User(h, h)


def in_memory_store(monkeypatch):
    """terms.accepted / terms.accept over a set; TERMS_VERSION is read at call time, as in the real ones."""
    store = set()

    async def accepted(sub):
        return (sub, terms.TERMS_VERSION) in store

    async def accept(sub):
        store.add((sub, terms.TERMS_VERSION))

    monkeypatch.setattr(terms, "accepted", accepted)
    monkeypatch.setattr(terms, "accept", accept)
    return store


@pytest.fixture
def gate(ids, tmp_path, monkeypatch):   # noqa: F811
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<p>site</p>")
    (tmp_path / "static" / "discover.html").write_text("<p>discover</p>")
    (tmp_path / "static" / "assets").mkdir()
    (tmp_path / "static" / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(authen, "user", fake_user)
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    monkeypatch.setitem(authen.AUTH, "mode", "access")   # the gate is on without a database
    in_memory_store(monkeypatch)
    with TestClient(app.app(str(tmp_path / "static"))) as c:
        yield c


def refused(r):
    return r.status_code == 403 and (r.json() == {"detail": terms.TERMS_REQUIRED} if r.headers[
        "content-type"].startswith("application/json") else 'id="accept"' in r.text)


def gated_still(r):
    """True if the terms gate (not the route) answered."""
    return terms.TERMS_REQUIRED in r.text or 'id="accept"' in r.text


def api_routes():
    for route in app.app().routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            path = route.path.replace("{id}", str(uuid.uuid4())).replace("{cohort_id}", "v1-0000000000000000")
            yield from ((m, path, route.path) for m in route.methods)


def test_unaccepted_user_is_refused_everywhere(gate):
    checked = 0
    for method, path, template in api_routes():
        if template in OPEN | {terms.ACCEPT_PATH}:
            continue
        r = gate.request(method, path, json={} if method in ("POST", "PUT", "PATCH") else None, headers=HDR)
        assert r.status_code == 403 and r.json() == {"detail": terms.TERMS_REQUIRED}, (method, template)
        checked += 1
    assert checked > 10
    r = gate.post("/mcp", json=COUNT_CALL, headers=MCP_HEADERS | HDR)
    assert r.status_code == 403 and r.json() == {"detail": terms.TERMS_REQUIRED}
    assert gate.post("/api/cohort", json={}, headers=HDR).json() == {"detail": terms.TERMS_REQUIRED}
    for method, path in GATED:
        r = gate.request(method, path, headers=HDR | {"accept": "application/json"})
        assert refused(r), (method, path)
    for path in ("/discover", "/discover.html", "/index.html", "/no/such/path"):
        r = gate.get(path, headers={"x-test-user": A})
        assert r.status_code == 403 and r.headers["content-type"].startswith("text/html"), path
        assert html.escape(terms.TERMS_TEXT) in r.text and terms.TERMS_VERSION in r.text and 'id="accept"' in r.text
        assert r.headers["cache-control"] == "no-store"
    assert gate.get("/mcp", headers=HDR).json() == {"detail": terms.TERMS_REQUIRED}


def test_open_routes_stay_open_for_an_unaccepted_user(gate):
    h = {"x-test-user": A}
    assert gate.get("/api/health", headers=h).status_code == 200
    assert gate.get("/api/public/summary", headers=h).status_code == 200
    assert gate.get("/", headers=h).text == "<p>site</p>"
    assert gate.get("/assets/app.js", headers=h).status_code == 200


def test_accept_opens_every_route(gate):
    assert gate.post(terms.ACCEPT_PATH, json=ACCEPT, headers=HDR).status_code == 200
    for method, path in GATED:
        r = gate.request(method, path, headers=HDR)
        assert not gated_still(r), (method, path)
    assert gate.get("/discover", headers=HDR).text == "<p>discover</p>"
    r = gate.post("/mcp", json=COUNT_CALL, headers=MCP_HEADERS | HDR)
    assert r.status_code == 200 and not r.json()["result"]["isError"]


def test_accept_wrong_version_is_409(gate):
    r = gate.post(terms.ACCEPT_PATH, json={"version": "1999-01-01"}, headers=HDR)
    assert r.status_code == 409
    assert gated_still(gate.get("/api/me", headers=HDR))


def test_accept_needs_json(gate):
    r = gate.post(terms.ACCEPT_PATH, content='{"version": "%s"}' % terms.TERMS_VERSION,
                  headers=HDR | {"content-type": "text/plain"})
    assert r.status_code == 422
    assert gated_still(gate.get("/api/me", headers=HDR))


def test_accept_needs_login(gate):
    assert gate.post(terms.ACCEPT_PATH, json=ACCEPT, headers={"accept": "application/json"}).status_code == 401


def test_version_bump_asks_again(gate, monkeypatch):
    assert gate.post(terms.ACCEPT_PATH, json=ACCEPT, headers=HDR).status_code == 200
    assert gate.get("/api/me", headers=HDR).status_code == 200
    monkeypatch.setattr(terms, "TERMS_VERSION", "2099-01-01")
    assert gated_still(gate.get("/api/me", headers=HDR))
    assert "2099-01-01" in gate.get("/discover", headers={"x-test-user": A}).text


def test_page():
    with_out, without = terms.page(True), terms.page(False)
    assert 'id="sign-out"' in with_out.body.decode() and 'id="sign-out"' not in without.body.decode()
    assert with_out.status_code == 403 and with_out.headers["cache-control"] == "no-store"
    body = without.body.decode()
    assert 'lang="en"' in body and 'name="viewport"' in body


@pytest.mark.parametrize("mode", authen.MODES)
@pytest.mark.parametrize("engine", [None, object()])
def test_gate_on(mode, engine, monkeypatch):
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    monkeypatch.setitem(authen.AUTH, "mode", mode)
    monkeypatch.setattr(saved, "_engine", engine)
    assert terms.gate_on() is not (mode in ("none", "password") and engine is None)


def test_fails_closed_without_a_database(ids, monkeypatch):   # noqa: F811
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(authen, "user", fake_user)
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    monkeypatch.setitem(authen.AUTH, "mode", "access")
    with TestClient(app.app()) as c:
        r = c.get("/api/me", headers=HDR)
    assert r.status_code == 503


@pytest.mark.parametrize("mode, env", [
    ("access", {"ACCESS_TEAM": "team", "ACCESS_AUD": "aud"}),
    ("authentik", {"AUTHENTIK_ISSUER": "https://id.example.test/o/x/", "AUTHENTIK_CLIENT_ID": "x",
                   "AUTHENTIK_CLIENT_SECRET": "y", "APP_BASE_URL": "http://testserver", "SESSION_SECRET": "s" * 48})])
def test_main_needs_a_database(mode, env, monkeypatch):
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    def no_run(*a, **kw):
        pytest.fail("uvicorn.run reached")
    monkeypatch.setattr(uvicorn, "run", no_run)
    with pytest.raises(SystemExit) as e:
        app.main(["--auth", mode])
    assert "DATABASE_URL" in str(e.value)


def test_signed_in_authentik_user_sees_terms_with_sign_out(c, issuer, monkeypatch):   # noqa: F811
    store = in_memory_store(monkeypatch)
    sign_in(c, issuer)
    r = c.get("/discover")
    assert r.status_code == 403 and 'id="sign-out"' in r.text and 'id="accept"' in r.text
    assert c.post("/auth/logout").status_code == 200
    sign_in(c, issuer)
    assert c.post(terms.ACCEPT_PATH, json=ACCEPT).status_code == 200
    assert store
    assert c.get("/discover").status_code == 200


# --- with Postgres -------------------------------------------------------------------------------

def run(fn, *args):
    """fn(*args) on a fresh engine, as the app's lifespan would start one."""
    async def go():
        saved.start(saved.database_url())
        try:
            return await fn(*args)
        finally:
            await saved.stop()
    return asyncio.run(go())


def test_acceptance_is_stored(clean, monkeypatch):   # noqa: F811
    assert run(terms.accepted, A) is False
    run(terms.accept, A)
    (row,) = sql("SELECT * FROM terms_acceptance")
    assert row["sub"] == A and row["terms_version"] == terms.TERMS_VERSION and row["accepted_at"] is not None
    run(terms.accept, A)
    assert sql("SELECT * FROM terms_acceptance") == [row]
    terms._accepted.clear()
    assert run(terms.accepted, A) is True
    monkeypatch.setattr(terms, "TERMS_VERSION", "2099-01-01")
    assert run(terms.accepted, A) is False
    assert len(sql("SELECT * FROM terms_acceptance")) == 1


def test_gate_end_to_end_with_postgres(ids, clean, monkeypatch):   # noqa: F811
    monkeypatch.setattr(authen, "user", fake_user)
    with TestClient(app.app()) as c:   # password mode, a database: the gate is on
        assert c.get("/api/saved", headers=HDR).status_code == 403
        assert c.post(terms.ACCEPT_PATH, json=ACCEPT, headers=HDR).status_code == 200
        assert c.get("/api/saved", headers=HDR).status_code == 200
    assert len(sql("SELECT * FROM terms_acceptance")) == 1


def test_migration_0003_round_trip(clean):   # noqa: F811
    cfg = Config(str(REPO / "mcp" / "alembic.ini"))
    exists = "SELECT to_regclass('terms_acceptance') IS NOT NULL AS t"
    try:
        command.downgrade(cfg, "0002")
        assert sql(exists) == [{"t": False}]
    finally:
        command.upgrade(cfg, "head")
    assert sql(exists) == [{"t": True}]
