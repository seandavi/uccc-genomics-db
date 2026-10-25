"""Saved cohorts in Postgres over REST and MCP (docs/specs/36-*.md).

Synthetic #34 mart in a temp dir plus a throwaway Postgres given by TEST_DATABASE_URL (the tests drop
and recreate its schema). Never $DATA/raw, the PHI file, the real de-id file or the real DATABASE_URL.
Every scripted case goes through both surfaces and must give the same JSON.
"""
import asyncio
import datetime
import json
import os
import re
from collections import namedtuple
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.testclient import TestClient

from test_app import MCP_HEADERS, ids, mart_file, walk  # noqa: F401  (fixtures)
from uccc_genomics_mcp import app, authen, cohort, saved

REPO = Path(__file__).resolve().parent.parent
A, B = "a@x.edu", "b@x.edu"
KRAS = {"kind": "alteration", "gene": ["KRAS"], "aa": ["G12C"]}
START = {"name": "x", "population": {"oncotree": ["NSCLC"]}}
COUNTED = {"population": {"oncotree": ["NSCLC"]}, "criteria": [{"id": "c1", **KRAS}]}
UNDER_FLOOR = {"population": {"oncotree": ["NSCLC"]},
               "criteria": [{"id": "c1", **KRAS}, {"id": "c2", "kind": "alteration", "gene": ["ALK"], "class": ["fusion"]}]}
UUID_OR_TIME = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.*)$")


@pytest.fixture(scope="module")
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("saved cohorts: set TEST_DATABASE_URL to a throwaway Postgres to run these (README)")
    if url == os.environ.get("DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL equals DATABASE_URL: these tests drop the schema")
    cfg = Config(str(REPO / "mcp" / "alembic.ini"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        command.check(cfg)
    return url


def sql(statement, **params):
    """Run one statement on a short-lived engine (DATABASE_URL, set by `clean`); the rows as dicts."""
    async def go():
        engine = create_async_engine(saved.database_url())
        try:
            async with engine.begin() as conn:
                result = await conn.execute(sa.text(statement), params)
                return [dict(r._mapping) for r in result.all()] if result.returns_rows else []
        finally:
            await engine.dispose()
    return asyncio.run(go())


@pytest.fixture
def clean(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    sql("TRUNCATE snapshot, cohort_revision, cohort, cohort_version")
    return pg_url


@pytest.fixture
def sclient(ids, clean, monkeypatch):
    def fake(request):
        try:
            return request.headers["x-test-user"]
        except KeyError:
            raise PermissionError("no test user") from None
    monkeypatch.setattr(authen, "user", fake)
    with TestClient(app.app()) as c:
        c.ids = ids
        yield c


Resp = namedtuple("Resp", "code body")   # code: HTTP status, or 200 / None (isError) for MCP


class Rest:
    """The saved-cohort calls over /api/*."""

    def __init__(self, c, user=A):
        self.c, self.user = c, user

    def _(self, method, path, body=None):
        r = self.c.request(method, path, json=body, headers={"x-test-user": self.user})
        return Resp(r.status_code, r.json())

    def save(self, d): return self._("POST", "/api/saved", d)
    def list(self): return self._("GET", "/api/saved")
    def get(self, id): return self._("GET", f"/api/saved/{id}")
    def apply(self, id, op): return self._("POST", f"/api/saved/{id}/apply", {"op": op})
    def history(self, id): return self._("GET", f"/api/saved/{id}/history")
    def revert(self, id, to): return self._("POST", f"/api/saved/{id}/revert", {"to": to})
    def snapshot(self, id): return self._("POST", f"/api/saved/{id}/snapshot")
    def delete(self, id): return self._("DELETE", f"/api/saved/{id}")
    def snapshots(self): return self._("GET", "/api/snapshots")
    def version(self, cid): return self._("GET", f"/api/versions/{cid}")
    def count(self, d): return self._("POST", "/api/cohort", d)


class Mcp(Rest):
    """The same calls as MCP tools; an isError result is Resp(None, text)."""

    def _tool(self, name, args):
        r = self.c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": name, "arguments": args}},
                        headers=MCP_HEADERS | {"x-test-user": self.user})
        res = r.json()["result"]
        return Resp(None, res["content"][0]["text"]) if res["isError"] else Resp(200, res["structuredContent"])

    def save(self, d): return self._tool("save_cohort", {"definition": d})
    def list(self): return self._tool("list_saved_cohorts", {})
    def get(self, id): return self._tool("get_saved_cohort", {"id": id})
    def apply(self, id, op): return self._tool("apply_saved_op", {"id": id, "op": op})
    def history(self, id): return self._tool("saved_cohort_history", {"id": id})
    def revert(self, id, to): return self._tool("revert_saved_cohort", {"id": id, "to": to})
    def snapshot(self, id): return self._tool("snapshot_saved_cohort", {"id": id})
    def delete(self, id): return self._tool("delete_saved_cohort", {"id": id})
    def snapshots(self): return self._tool("list_snapshots", {})
    def version(self, cid): return self._tool("get_cohort_version", {"cohort_id": cid})
    def count(self, d): return self._tool("count", {"definition": d})


def mask(x):
    if isinstance(x, dict):
        return {k: mask(v) for k, v in x.items()}
    if isinstance(x, list):
        return [mask(v) for v in x]
    return "*" if isinstance(x, str) and UUID_OR_TIME.match(x) else x


def ok(r):
    assert r.code == 200, r
    return r.body


def script(s):
    out = []
    id = ok(s.save(START))["id"]
    out.append(s.get(id))
    out.append(s.apply(id, {"op": "add_criterion", "criterion": KRAS}))
    out.append(s.apply(id, {"op": "rename", "name": "kras"}))
    out.append(s.apply(id, {"op": "set_breakdown", "breakdown": ["sex"]}))
    out.append(s.revert(id, 1))
    out.append(s.history(id))
    out.append(s.snapshot(id))
    out.append(s.snapshots())
    out.append(s.list())
    out.append(s.delete(id))
    out.append(s.list())
    return out


def test_saved_parity(sclient):
    rest, mcp = script(Rest(sclient, A)), script(Mcp(sclient, B))   # snapshots outlive their cohort, so another user
    assert all(r.code == 200 for r in rest + mcp)
    for r, m in zip(rest, mcp):
        assert mask(r.body) == mask(m.body)


def test_saved_reads_are_identical(sclient):
    rest, mcp = Rest(sclient), Mcp(sclient)
    id = ok(rest.save(START))["id"]
    ok(rest.apply(id, {"op": "add_criterion", "criterion": KRAS}))
    ok(rest.snapshot(id))
    cid = ok(rest.get(id))["head"]["cohort_id"]
    for call in (lambda s: s.get(id), lambda s: s.history(id), lambda s: s.list(), lambda s: s.snapshots(),
                 lambda s: s.version(cid)):
        r, m = call(rest), call(mcp)
        assert r.code == m.code == 200 and r.body == m.body


def test_revisions(sclient):
    s = Rest(sclient)
    first = ok(s.save(START))
    id = first["id"]
    assert first["head"]["seq"] == 1 and first["head"]["op"] is None
    renamed = ok(s.apply(id, {"op": "rename", "name": "renamed"}))
    assert renamed["head"]["seq"] == 2 and renamed["head"]["op"]["op"] == "rename"
    assert renamed["head"]["cohort_id"] == first["head"]["cohort_id"]
    assert renamed["head"]["definition"]["name"] == "renamed"
    added = ok(s.apply(id, {"op": "add_criterion", "criterion": KRAS}))
    assert added["head"]["seq"] == 3 and added["head"]["cohort_id"] != first["head"]["cohort_id"]
    before = ok(s.history(id))["revisions"]
    reverted = ok(s.revert(id, 1))
    assert reverted["head"]["seq"] == 4 and reverted["head"]["op"] == {"op": "revert", "to": 1}
    assert reverted["head"]["definition"] == first["head"]["definition"]
    after = ok(s.history(id))["revisions"]
    assert after[:3] == before and [r["seq"] for r in after] == [1, 2, 3, 4]
    assert ok(s.revert(id, 4))["head"]["seq"] == 5   # reverting to the head is a no-op revision


def test_ownership(sclient):
    ra, rb = Rest(sclient, A), Rest(sclient, B)
    id = ok(ra.save(START))["id"]
    ok(ra.snapshot(id))
    mine = ok(ra.get(id))
    for s in (rb, Mcp(sclient, B)):
        for r in (s.get(id), s.apply(id, {"op": "rename", "name": "stolen"}), s.history(id), s.revert(id, 1),
                  s.snapshot(id), s.delete(id)):
            assert r.code in (404, None) and "no saved cohort" in json.dumps(r.body)
        assert ok(s.list()) == {"cohorts": []} and ok(s.snapshots()) == {"snapshots": []}
    assert ok(ra.get(id)) == mine and len(ok(ra.snapshots())["snapshots"]) == 1
    version = ok(rb.version(mine["head"]["cohort_id"]))
    copy = ok(rb.save(version["definition"]))
    assert copy["id"] != id and ok(ra.get(id)) == mine


def test_cohort_version_is_content_addressed(sclient):
    d = {"population": {"oncotree": ["NSCLC"]}, "criteria": [{"id": "c1", **KRAS}]}
    ra, rb = Rest(sclient, A), Mcp(sclient, B)
    ok(ra.save(d | {"name": "first", "breakdown": ["sex"]}))
    cid = ok(rb.save(d | {"name": "second", "breakdown": ["vendor"]}))["head"]["cohort_id"]
    assert len(sql("SELECT * FROM cohort_version")) == 1
    for s in (ra, rb):
        v = ok(s.version(cid))
        assert v["definition"]["name"] == "" and v["definition"]["breakdown"] == [] and v["definition"]["pivot"] is None
        assert v["definition"]["criteria"][0]["gene"] == ["KRAS"]
        assert "created_by" not in {k for k, _ in walk(v)}
    stored = sql("SELECT definition FROM cohort_version")[0]["definition"]
    assert (stored["name"], stored["breakdown"], stored["pivot"]) == ("", [], None)
    missing = "v1-0000000000000000"
    assert Rest(sclient).version(missing).code == 404
    r = Mcp(sclient).version(missing)
    assert r.code is None and "no cohort version" in r.body


def test_snapshot(sclient, capsys, monkeypatch):
    rest, mcp = Rest(sclient), Mcp(sclient)
    id = ok(rest.save(COUNTED))["id"]
    capsys.readouterr()
    snap = ok(rest.snapshot(id))
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines()]
    assert len(lines) == 1 and (lines[0]["email"], lines[0]["endpoint"], lines[0]["surface"]) == (A, "count", "rest")
    assert snap["result"] == ok(rest.count(COUNTED)) and snap["data_date"] == cohort.data_date().isoformat()
    assert snap["definition"] == ok(rest.get(id))["head"]["definition"]
    small = ok(rest.save(UNDER_FLOOR))
    result = ok(mcp.snapshot(small["id"]))["result"]
    assert result["loosen"]
    for k, v in walk(result):
        if k in ("patients", "denominator", "reports") and isinstance(v, int):
            assert not 1 <= v <= 4
    monkeypatch.setattr(app, "RATE_LIMIT", 1)
    app._calls.clear()
    ok(rest.snapshot(id))
    n = len(ok(rest.snapshots())["snapshots"])
    refused = rest.snapshot(id)
    assert refused.code == 429
    m = mcp.snapshot(id)
    assert m.code is None and "rate limit" in m.body
    assert len(ok(rest.snapshots())["snapshots"]) == n


def test_nothing_small_or_identifying_stored(sclient):
    for s in (Rest(sclient), Mcp(sclient)):
        script(s)
        id = ok(s.save(UNDER_FLOOR))["id"]
        ok(s.snapshot(id))
        ok(s.save({"population": {"oncotree": ["STAD"]}, "criteria": [{"id": "c1", "kind": "ihc", "marker": "CLDN18"}]}))
    for table in ("cohort_version", "cohort", "cohort_revision", "snapshot"):
        rows = sql(f"SELECT * FROM {table}")
        assert rows or table == "cohort_version"
        for row in rows:
            for k, v in walk(json.loads(json.dumps(row, default=str))):
                assert k not in ("research_id", "report_id")
                assert not (isinstance(v, str) and v in sclient.ids), (table, k, v)
                if table != "snapshot":
                    assert k not in ("patients", "denominator", "reports")
    for row in sql("SELECT result FROM snapshot"):
        for k, v in walk(row["result"]):
            if k in ("patients", "denominator", "reports") and isinstance(v, int):
                assert not 1 <= v <= 4


ERRORS = [   # (name, call on a surface given an owned cohort id, REST status, word in both messages)
    ("unknown id", lambda s, id: s.get("00000000-0000-4000-8000-000000000000"), 404, "no saved cohort"),
    ("malformed id", lambda s, id: s.get("not-a-uuid"), 422, "uuid"),
    ("bad gene on save", lambda s, id: s.save({"criteria": [{"id": "c1", "kind": "alteration", "gene": ["NOTAGENE"]}]}),
     400, "gene"),
    ("bad gene on apply", lambda s, id: s.apply(id, {"op": "add_criterion",
                                                      "criterion": {"kind": "alteration", "gene": ["NOTAGENE"]}}), 400, "gene"),
    ("unknown op", lambda s, id: s.apply(id, {"op": "explode"}), 422, "op"),
    ("no such revision", lambda s, id: s.revert(id, 99), 404, "no revision"),
]


@pytest.mark.parametrize("name, call, status, word", ERRORS, ids=[e[0] for e in ERRORS])
def test_saved_errors_agree(sclient, name, call, status, word):
    id = ok(Rest(sclient).save(START))["id"]
    r, m = call(Rest(sclient), id), call(Mcp(sclient), id)
    assert r.code == status and word in json.dumps(r.body).lower()
    assert m.code is None and word in m.body.lower()


def test_caps(sclient, monkeypatch):
    monkeypatch.setattr(saved, "MAX_COHORTS", 1)
    monkeypatch.setattr(saved, "MAX_REVISIONS", 2)
    monkeypatch.setattr(saved, "MAX_SNAPSHOTS", 1)
    rest, mcp = Rest(sclient), Mcp(sclient)
    id = ok(rest.save(START))["id"]
    assert rest.save(START).code == 409 and mcp.save(START).code is None
    assert ok(mcp.apply(id, {"op": "rename", "name": "two"}))["head"]["seq"] == 2
    assert rest.apply(id, {"op": "rename", "name": "three"}).code == 409
    assert mcp.apply(id, {"op": "rename", "name": "three"}).code is None
    assert rest.revert(id, 1).code == 409 and mcp.revert(id, 1).code is None
    ok(rest.snapshot(id))
    assert rest.snapshot(id).code == 409 and mcp.snapshot(id).code is None
    assert Rest(sclient, B).save(START).code == 200   # caps are per user


def test_stale_append_conflicts(clean):
    async def go():
        saved.start(saved.database_url())
        try:
            c = await saved.create(A, cohort.parse(START))
            renamed = cohort.parse(START | {"name": "y"})
            await saved.append(A, c.id, renamed, {"op": "rename", "name": "y"}, after=1)
            with pytest.raises(saved.Conflict):
                await saved.append(A, c.id, renamed, {"op": "rename", "name": "z"}, after=1)
            with pytest.raises(saved.NotFound):
                await saved.append(B, c.id, renamed, {"op": "rename", "name": "z"}, after=2)
        finally:
            await saved.stop()
    asyncio.run(go())


def test_delete(sclient):
    rest = Rest(sclient)
    id = ok(rest.save(COUNTED))["id"]
    cid = ok(rest.get(id))["head"]["cohort_id"]
    ok(rest.snapshot(id))
    assert ok(rest.delete(id)) == {"id": id}
    for r in (rest.get(id), rest.history(id), rest.apply(id, {"op": "rename", "name": "z"}), rest.delete(id)):
        assert r.code == 404
    assert len(ok(rest.snapshots())["snapshots"]) == 1
    assert [r["cohort_id"] for r in sql("SELECT cohort_id FROM cohort_version")] == [cid]
    assert sql("SELECT * FROM cohort_revision") == []


def test_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert saved.database_url() is None
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    url = saved.database_url()
    assert (url.drivername, url.host, url.port, url.database) == ("postgresql+asyncpg", "h", 5432, "d")


def test_data_date_is_a_date(ids):
    assert isinstance(cohort.data_date(), datetime.date)
