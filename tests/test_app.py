"""genomics-app: REST and MCP over the cohort module, behind authen (docs/specs/35-*.md).

Runs on the synthetic #34 mart in a temp dir; no network, never $DATA/raw, the PHI file or the real
de-id file. Every parity case goes through both surfaces and must give identical JSON.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from test_cohort import build_mart, use_mart, write_mart
from uccc_genomics_mcp import app, authen, server

ROOT = Path(__file__).resolve().parent.parent
AUTH = ("sean", "s3cret")
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def mart_file(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("app") / "cohort.duckdb")
    m = build_mart()
    write_mart(path, m)
    return path, m


@pytest.fixture
def ids(mart_file, monkeypatch):
    path, m = mart_file
    info = use_mart(path, m, monkeypatch)
    monkeypatch.setattr(app, "get_db", lambda: server.harden(duckdb.connect(path, read_only=True)))
    monkeypatch.setattr(app, "_calls", {})
    monkeypatch.setenv("APP_USER", "sean")
    monkeypatch.setenv("APP_PASSWORD_HASH", authen.hash_password("s3cret"))
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    authen.configure("password")
    return info["ids"]


@pytest.fixture
def client(ids, tmp_path):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<p>site</p>")
    with TestClient(app.app(str(tmp_path / "static"))) as c:
        yield c


def rpc(c, method, params, auth=AUTH, headers=None):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, auth=auth,
               headers=MCP_HEADERS | (headers or {}))
    return r.json()["result"] if r.status_code == 200 else r


def mcp_call(c, tool, args, **kw):
    return rpc(c, "tools/call", {"name": tool, "arguments": args}, **kw)


def mcp_list(c, **kw):
    return rpc(c, "tools/list", {}, **kw)


def walk(x):
    """Every (key, value) pair anywhere in a response."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield None, v
            yield from walk(v)


def alt(cid, gene, **kw):
    return {"id": cid, "kind": "alteration", "gene": gene, **kw}


def ihc(cid, marker, **kw):
    return {"id": cid, "kind": "ihc", "marker": marker, **kw}


KRAS = alt("c1", ["KRAS"], aa=["G12C"])
NSCLC = {"oncotree": ["NSCLC"]}
STAD = {"oncotree": ["STAD"]}
START = {"criteria": [alt("c1", ["KRAS"])]}


def count(d):
    return ("POST", "/api/cohort", d, "count", {"definition": d})


def pivot_case(d):
    return ("POST", "/api/pivot", d, "pivot", {"definition": d})


def apply_case(op, d=START):
    return ("POST", "/api/apply", {"definition": d, "op": op}, "apply_op", {"definition": d, "op": op})


def options(q, **kw):
    return ("GET", "/api/options?" + urlencode({"q": q, **kw}), None, "search_vocabulary", {"q": q, **kw})


CASES = [
    count({}),
    count({"population": NSCLC, "criteria": [KRAS]}),
    count({"population": {"oncotree": ["COADREAD"]},
           "criteria": [{"id": "c1", "kind": "biomarker", "name": "MSI", "call": ["high"]}],
           "breakdown": ["sex", "vendor"]}),
    count({"population": NSCLC, "criteria": [KRAS, alt("c2", ["ALK"], **{"class": ["fusion"]})]}),   # under the floor: loosen[]
    count({"population": STAD, "criteria": [
        {"id": "c1", "kind": "any_of", "of": [{"kind": "ihc", "marker": "CLDN18", "call": ["positive"]},
                                              {"kind": "ihc", "marker": "PD-L1", "measure": "CPS", "at_least": 10}]}]}),
    pivot_case({"pivot": {"rows": "oncotree", "cols": "year"}}),
    pivot_case({"population": STAD, "criteria": [ihc("c1", "CLDN18")], "pivot": {"rows": "c1.val", "cols": "vendor"}}),
    apply_case({"op": "add_criterion", "criterion": {"kind": "biomarker", "name": "MSI", "call": ["high"]}}),
    apply_case({"op": "remove_criterion", "id": "c1"}),
    apply_case({"op": "update_criterion", "id": "c1", "criterion": alt("c1", ["ALK"])}),
    apply_case({"op": "set_population", "population": NSCLC}),
    apply_case({"op": "set_breakdown", "breakdown": ["sex", "vendor"]}),
    apply_case({"op": "set_pivot", "pivot": {"rows": "oncotree", "cols": "year"}}),
    apply_case({"op": "set_pivot", "pivot": None}, {"pivot": {"rows": "oncotree", "cols": "year"}}),
    apply_case({"op": "rename", "name": "my cohort"}),
    options("kras"), options("her2"), options(""), options("r", limit=2),
    options("", field="population.sex"), options("", field="alteration.aa", parent="KRAS", limit=50),
    options("", field="biomarker.call", parent="MSI"),
    ("GET", "/api/schema", None, "describe_definition", {}),
]
IDS = [f"{c[3]}-{i}" for i, c in enumerate(CASES)]


def rest(c, method, path, payload):
    return c.request(method, path, json=payload, auth=AUTH)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_parity(client, case):
    method, path, payload, tool, args = case
    r = rest(client, method, path, payload)
    m = mcp_call(client, tool, args)
    assert r.status_code == 200, r.text
    assert not m["isError"], m
    assert r.json() == m["structuredContent"]


def test_parity_cases_are_not_trivial(client):
    """Guard the parity test: the loosen case really loosens and the pivot has cells."""
    loosen = rest(client, *CASES[3][:3]).json()
    assert loosen["loosen"]
    assert rest(client, *CASES[5][:3]).json()["cells"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_no_small_numbers_and_no_ids(client, ids, case):
    method, path, payload, tool, args = case
    bodies = [rest(client, method, path, payload).json(), mcp_call(client, tool, args)["structuredContent"]]
    for body in bodies:
        for k, v in walk(body):
            assert k not in ("research_id", "report_id")
            if k in ("patients", "denominator", "reports"):
                assert not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4), (k, v)
            assert not (isinstance(v, str) and v in ids), (k, v)
    if tool == "search_vocabulary":
        assert all("patients" not in e for b in bodies for e in b["entries"])


ERRORS = [
    ("POST", "/api/cohort", {"scope": "report"}, "count", {"definition": {"scope": "report"}}, "scope"),
    ("POST", "/api/cohort", {"criteria": [alt("c1", ["NOTAGENE"])]}, "count",
     {"definition": {"criteria": [alt("c1", ["NOTAGENE"])]}}, "gene"),
    ("POST", "/api/pivot", {}, "pivot", {"definition": {}}, "pivot"),
    ("POST", "/api/apply", {"definition": START, "op": {"op": "remove_criterion", "id": "c9"}}, "apply_op",
     {"definition": START, "op": {"op": "remove_criterion", "id": "c9"}}, "c9"),
    ("POST", "/api/apply", {"definition": START, "op": {"op": "explode"}}, "apply_op",
     {"definition": START, "op": {"op": "explode"}}, "op"),
]


@pytest.mark.parametrize("method, path, payload, tool, args, word", ERRORS, ids=[e[5] for e in ERRORS])
def test_errors_agree(client, method, path, payload, tool, args, word):
    r = rest(client, method, path, payload)
    m = mcp_call(client, tool, args)
    assert r.status_code in (400, 422)
    assert word in json.dumps(r.json()["detail"])
    assert m["isError"]
    assert word in m["content"][0]["text"]


def test_tools_list(client):
    tools = {t["name"]: t for t in mcp_list(client)["tools"]}
    assert set(tools) == {"search_vocabulary", "apply_op", "count", "pivot", "describe_definition"}
    assert "definition" in tools["count"]["inputSchema"]["properties"]
    assert "definition" in tools["pivot"]["inputSchema"]["properties"]
    assert "patients" not in json.dumps(tools["search_vocabulary"]["outputSchema"])


def test_openapi_names_the_models(client):
    schemas = client.get("/api/openapi.json", auth=AUTH).json()["components"]["schemas"]
    assert {"Definition", "CountResult", "PivotResult", "ApplyRequest", "ApplyResult", "Options",
            "SchemaInfo"} <= set(schemas)


GATED = [("POST", "/api/cohort"), ("POST", "/api/pivot"), ("POST", "/api/apply"), ("GET", "/api/options"),
         ("GET", "/api/schema"), ("GET", "/api/openapi.json"), ("GET", "/api/docs"), ("POST", "/mcp"),
         ("GET", "/mcp"), ("GET", "/"), ("GET", "/index.html"), ("GET", "/no/such/path")]


@pytest.mark.parametrize("method, path", GATED)
def test_refused_without_login(client, method, path):
    # Accept: json, because an authenticated GET /mcp that accepts */* opens the SDK's endless SSE stream
    kw = {"headers": {"accept": "application/json"}}
    r = client.request(method, path, **kw)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert client.request(method, path, auth=("sean", "wrong"), **kw).status_code == 401
    assert client.request(method, path, auth=AUTH, **kw).status_code != 401


def test_health_is_open(client):
    r = client.get("/api/health")
    assert (r.status_code, r.json()) == (200, {"status": "Healthy"})


def test_health_unhealthy(client, monkeypatch):
    def boom():
        raise RuntimeError("/secret/path is gone")
    monkeypatch.setattr(app, "get_db", boom)
    r = client.get("/api/health")
    assert (r.status_code, r.json()) == (503, {"status": "unhealthy"})


def test_access_backend(client, monkeypatch, capsys):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Jwks:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})

    monkeypatch.setitem(authen.AUTH, "mode", "access")
    monkeypatch.setitem(authen.AUTH, "team", "team")
    monkeypatch.setitem(authen.AUTH, "aud", "aud-tag")
    monkeypatch.setitem(authen.AUTH, "jwks", Jwks())

    def token(**claims):
        return jwt.encode({"email": "a@b.edu", "aud": "aud-tag", "iss": "https://team.cloudflareaccess.com"} | claims,
                          key, algorithm="RS256")

    def hdr(**claims):
        return {"cf-access-jwt-assertion": token(**claims)}

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "count", "arguments": {"definition": {}}}}
    for headers in ({}, hdr(aud="other")):
        assert client.post("/api/cohort", json={}, headers=headers).status_code == 401
        assert client.post("/mcp", json=body, headers=MCP_HEADERS | headers).status_code == 401
    capsys.readouterr()
    assert client.post("/api/cohort", json={}, headers=hdr()).status_code == 200
    r = client.post("/mcp", json=body, headers=MCP_HEADERS | hdr())
    assert r.status_code == 200 and not r.json()["result"]["isError"]
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [(line["surface"], line["email"]) for line in lines] == [("rest", "a@b.edu"), ("mcp", "a@b.edu")]


def test_audit(client, capsys):
    d = {"population": NSCLC, "criteria": [KRAS]}
    pd = {"pivot": {"rows": "oncotree", "cols": "year"}}
    capsys.readouterr()
    rc = rest(client, "POST", "/api/cohort", d).json()
    mp = mcp_call(client, "pivot", {"definition": pd})["structuredContent"]
    rest(client, "GET", "/api/options?q=kras", None)
    rest(client, "POST", "/api/apply", {"definition": START, "op": {"op": "rename", "name": "x"}})
    rest(client, "GET", "/api/schema", None)
    client.get("/api/health")
    rest(client, "POST", "/api/cohort", {"scope": "report"})
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert len(lines) == 2
    assert [(x["email"], x["surface"], x["endpoint"]) for x in lines] == [("sean", "rest", "count"), ("sean", "mcp", "pivot")]
    assert lines[0]["patients"] == rc["patients"] and lines[1]["patients"] == mp["patients"]
    assert lines[0]["cohort_id"] == app.cohort.cohort_id(app.Definition.model_validate(d))
    assert lines[0]["definition"]["criteria"][0]["gene"] == ["KRAS"]
    assert lines[1]["definition"]["pivot"] == pd["pivot"]


def test_rate_limit(client, monkeypatch, capsys):
    monkeypatch.setattr(app, "RATE_LIMIT", 3)
    pd = {"pivot": {"rows": "oncotree", "cols": "year"}}
    assert rest(client, "POST", "/api/cohort", {}).status_code == 200
    assert rest(client, "POST", "/api/cohort", {}).status_code == 200
    assert not mcp_call(client, "pivot", {"definition": pd})["isError"]
    capsys.readouterr()
    r = rest(client, "POST", "/api/cohort", {})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    m = mcp_call(client, "count", {"definition": {}})
    assert m["isError"] and "rate limit" in m["content"][0]["text"]
    assert capsys.readouterr().out == ""   # refused requests are not logged as queries
    assert rest(client, "GET", "/api/options?q=kras", None).status_code == 200
    assert rest(client, "POST", "/api/apply", {"definition": START, "op": {"op": "rename", "name": "x"}}).status_code == 200
    assert rest(client, "GET", "/api/schema", None).status_code == 200
    app.rate_limit("other@x")   # another user has their own budget
    monkeypatch.setattr(app, "RATE_WINDOW", 0.0)
    app.rate_limit("sean")


def test_mcp_tool_needs_the_middleware(ids):
    try:
        result = asyncio.run(app.mcp_app.call_tool("count", {"definition": {}}))
    except Exception:
        return
    assert getattr(result, "is_error", True) or getattr(result, "isError", True)
    assert "patients" not in str(result)


def test_openapi_snapshot():
    committed = json.loads((ROOT / "web" / "openapi.json").read_text())
    assert committed == app.app().openapi(), "web/openapi.json is stale: run `cd web && bun run gen`"
