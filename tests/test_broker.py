"""Honest-broker records: IRB registry, requests, reviews, releases, read-only over REST and MCP (docs/specs/132-*.md).

Synthetic #34 mart in a temp dir plus the throwaway Postgres of test_saved (TEST_DATABASE_URL). Seed rows are
inserted with SQL and hold synthetic values only. Never $DATA/raw, the PHI file, the real de-id file or the
real DATABASE_URL.
"""
import datetime
import json
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from starlette.testclient import TestClient

from test_app import MCP_HEADERS, ids, mart_file, walk  # noqa: F401  (fixtures)
from test_saved import A, B, COUNTED, START, Mcp, Rest, clean, ok, pg_url, sql  # noqa: F401
from uccc_genomics.deid import DROP
from uccc_genomics_mcp import app, authen

BROKER = "broker@x.edu"
SHA = "0" * 64
RESEARCH_IDS = ("0123456789abcdef", "fedcba9876543210")
JSON_COLUMNS = {"fields", "identifiers", "recipients", "checklist", "fields_released"}


@pytest.fixture
def bclient(ids, clean, monkeypatch):
    """A client whose test user comes from x-test-user, and is a broker with x-test-broker: 1."""
    def fake(request):
        try:
            h = request.headers["x-test-user"]
        except KeyError:
            raise PermissionError("no test user") from None
        return authen.User(h, h, request.headers.get("x-test-broker") == "1")
    monkeypatch.setattr(authen, "user", fake)
    with TestClient(app.app()) as c:
        yield c


class Surface:
    """The six read calls on one surface; `broker` adds the broker header (REST) or sets the user's flag."""

    def __init__(self, c, user=A, broker=False):
        self.c, self.user, self.broker = c, user, broker

    def headers(self):
        return {"x-test-user": self.user} | ({"x-test-broker": "1"} if self.broker else {})


class RestReads(Surface):
    def _(self, path):
        r = self.c.get(path, headers=self.headers())
        return r.status_code, r.json()

    def mine(self): return self._("/api/requests")
    def my(self, id): return self._(f"/api/requests/{id}")
    def requests(self, status=None): return self._("/api/broker/requests" + (f"?status={status}" if status else ""))
    def request(self, id): return self._(f"/api/broker/requests/{id}")
    def irbs(self): return self._("/api/broker/irb")
    def irb(self, n): return self._(f"/api/broker/irb/{n}")


class McpReads(Surface):
    def _(self, name, args=None):
        r = self.c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": name, "arguments": args or {}}},
                        headers=MCP_HEADERS | self.headers())
        res = r.json()["result"]
        return (None, res["content"][0]["text"]) if res["isError"] else (200, res["structuredContent"])

    def mine(self): return self._("list_my_requests")
    def my(self, id): return self._("get_my_request", {"id": str(id)})
    def requests(self, status=None): return self._("broker_list_requests", {"status": status} if status else {})
    def request(self, id): return self._("broker_get_request", {"id": str(id)})
    def irbs(self): return self._("broker_list_irb")
    def irb(self, n): return self._("broker_get_irb", {"irb_number": n})


SURFACES = [RestReads, McpReads]


def seed(c):
    """IRB TEST-0001 v1 and v2, a saved cohort of A, and one submitted request on its first revision with a
    review and a release. Returns (request id, cohort id)."""
    cohort_id = uuid.UUID(ok(Rest(c, A).save(START))["id"])
    for v in (1, 2):
        sql("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, expiration_date, hipaa_pathway,"
            " approved_population, status, created_by) VALUES ('TEST-0001', :v, 'Dr Example', '2026-01-01',"
            " '2027-01-01', 'waiver', 'synthetic population', 'active', 'sub-x')", v=v)
    sql("INSERT INTO irb_document (id, irb_number, version, doc_type, file_ref, sha256, created_by, created_at) VALUES"
        " (:d2, 'TEST-0001', 1, 'protocol_excerpt', 'irb/b.pdf', :sha, 'sub-x', now()),"
        " (:d1, 'TEST-0001', 1, 'approval_letter', 'irb/a.pdf', :sha, 'sub-x', now() + interval '1 second')",
        d1=uuid.uuid4(), d2=uuid.uuid4(), sha=SHA)
    sql("INSERT INTO irb_personnel (irb_number, version, person_id, name, role) VALUES"
        " ('TEST-0001', 1, 'b@example.edu', 'B Example', 'coordinator'), ('TEST-0001', 1, 'a@example.edu', 'A Example', 'PI')")
    sql("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, hipaa_pathway, approved_population,"
        " status, created_by) VALUES ('TEST-0002', 1, 'Dr Other', '2026-02-01', 'authorization', 'synthetic', 'closed', 'sub-x')")
    req = uuid.uuid4()
    sql("INSERT INTO request (id, requester, cohort, seq, irb_number, irb_version, purpose, fields, identifiers,"
        " recipients, storage_location, retention_end, status) VALUES (:id, :who, :c, 1, 'TEST-0001', 1,"
        " 'synthetic purpose', CAST(:f AS jsonb), CAST(:i AS jsonb), CAST(:r AS jsonb), 'synthetic share',"
        " :ret, 'submitted')", id=req, who=A, c=cohort_id, ret=datetime.date(2027, 6, 1), f=json.dumps(["age_band", "oncotree"]),
        i=json.dumps([{"identifier": "mrn", "reason": "synthetic reason"}]),
        r=json.dumps([{"name": "R Example", "email": "r@example.edu"}]))
    sql("INSERT INTO review (id, request_id, reviewer, checklist, decision, notes) VALUES"
        " (:id, :req, :b, CAST(:ck AS jsonb), 'return', 'synthetic note')",
        id=uuid.uuid4(), req=req, b=BROKER, ck=json.dumps({"irb_active": True, "personnel": False}))
    release = uuid.uuid4()
    sql("INSERT INTO release (id, request_id, file_name, sha256, row_count, fields_released, recipients,"
        " sharepoint_link) VALUES (:id, :req, 'synthetic.csv', :sha, 12, CAST(:f AS jsonb), CAST(:r AS jsonb),"
        " 'https://example.test/file')", id=release, req=req, sha=SHA, f=json.dumps(["age_band"]),
        r=json.dumps([{"name": "R Example", "email": "r@example.edu"}]))
    for rid in RESEARCH_IDS:
        sql("INSERT INTO release_patient (release_id, research_id) VALUES (:r, :p)", r=release, p=rid)
    return req, cohort_id


@pytest.mark.parametrize("S", SURFACES)
def test_requester_sees_only_their_own(bclient, S):
    req, _ = seed(bclient)
    a, b = S(bclient, A), S(bclient, B)
    code, body = a.mine()
    assert code == 200 and [r["id"] for r in body["requests"]] == [str(req)]
    assert b.mine() == (200, {"requests": []})
    code, detail = a.my(req)
    assert code == 200 and detail["id"] == str(req) and detail["requester"] == A
    nobody = uuid.uuid4()
    other, missing = b.my(req), a.my(nobody)
    assert other[0] == missing[0] and other[0] in (404, None) and "no request" in json.dumps(other[1])
    assert json.dumps(other[1]).replace(str(req), "X") == json.dumps(missing[1]).replace(str(nobody), "X")


def test_rest_and_mcp_agree(bclient):
    req, _ = seed(bclient)
    r, m = RestReads(bclient, A, True), McpReads(bclient, A, True)
    for call in (lambda s: s.mine(), lambda s: s.my(req), lambda s: s.requests(), lambda s: s.request(req),
                 lambda s: s.irbs(), lambda s: s.irb("TEST-0001")):
        assert call(r) == call(m) and call(r)[0] == 200


@pytest.mark.parametrize("S", SURFACES)
def test_broker_gate(bclient, S):
    req, _ = seed(bclient)
    plain, broker = S(bclient, A), S(bclient, BROKER, True)
    for call in (lambda s: s.requests(), lambda s: s.request(req), lambda s: s.irbs(), lambda s: s.irb("TEST-0001")):
        code, body = call(plain)
        assert code in (403, None) and "honest broker only" in json.dumps(body)
        assert call(broker)[0] == 200
    assert [r["id"] for r in broker.requests()[1]["requests"]] == [str(req)]   # not the broker's own
    assert broker.requests("submitted")[1]["requests"] and broker.requests("closed")[1] == {"requests": []}
    assert broker.request(req)[1]["requester"] == A
    code, body = broker.irb("NOPE")
    assert code in (404, None) and "no IRB authorization NOPE" in json.dumps(body)


def test_bad_status_is_refused(bclient):
    code, _ = RestReads(bclient, BROKER, True).requests("bogus")
    assert code == 422
    code, text = McpReads(bclient, BROKER, True).requests("bogus")
    assert code is None and "status" in text


@pytest.mark.parametrize("S", SURFACES)
def test_irb_registry_shape_and_order(bclient, S):
    seed(bclient)
    s = S(bclient, BROKER, True)
    listed = s.irbs()[1]["authorizations"]
    assert [(a["irb_number"], a["version"]) for a in listed] == [("TEST-0001", 2), ("TEST-0002", 1)]
    irb = s.irb("TEST-0001")[1]
    assert [v["version"] for v in irb["versions"]] == [1, 2]
    v1, v2 = irb["versions"]
    assert [d["doc_type"] for d in v1["documents"]] == ["protocol_excerpt", "approval_letter"]   # created order
    assert [p["person_id"] for p in v1["personnel"]] == ["a@example.edu", "b@example.edu"]
    assert v2["documents"] == [] and v2["personnel"] == []
    assert v1["expiration_date"] == "2027-01-01" and listed[1]["expiration_date"] is None


@pytest.mark.parametrize("S", SURFACES)
def test_request_detail_is_frozen_to_its_revision(bclient, S):
    req, cohort_id = seed(bclient)
    rest = Rest(bclient, A)
    first = ok(rest.get(str(cohort_id)))["head"]
    ok(rest.apply(str(cohort_id), {"op": "rename", "name": "renamed"}))
    detail = S(bclient, A).my(req)[1]
    assert (detail["cohort"], detail["seq"]) == (str(cohort_id), 1)
    assert detail["cohort_id"] == first["cohort_id"] and detail["definition"] == first["definition"]
    assert detail["snapshot_id"] == "synthetic-build-1"
    assert ok(rest.get(str(cohort_id)))["head"]["seq"] == 2   # the head moved; the request did not
    assert detail["irb"]["irb_number"] == "TEST-0001" and detail["irb"]["version"] == 1
    assert [d["doc_type"] for d in detail["irb"]["documents"]] == ["protocol_excerpt", "approval_letter"]
    assert [r["decision"] for r in detail["reviews"]] == ["return"]
    assert detail["reviews"][0]["checklist"] == {"irb_active": True, "personnel": False}
    release = detail["releases"][0]
    assert release["row_count"] == 12 and release["fields_released"] == ["age_band"]
    assert detail["identifiers"] == [{"identifier": "mrn", "reason": "synthetic reason"}]


def test_a_draft_may_lack_an_irb(bclient):
    seed(bclient)
    cohort_id = uuid.UUID(ok(Rest(bclient, A).save(COUNTED))["id"])
    sql("INSERT INTO request (id, requester, cohort, seq, purpose, fields, identifiers, recipients, storage_location,"
        " status) VALUES (:id, :who, :c, 1, '', '[]', '[]', '[]', '', 'draft')", id=uuid.uuid4(), who=A, c=cohort_id)
    drafts = RestReads(bclient, A).mine()[1]["requests"]
    assert len(drafts) == 2 and {r["irb_number"] for r in drafts} == {None, "TEST-0001"}
    assert all(r["irb"] is None for r in (RestReads(bclient, A).my(d["id"])[1] for d in drafts if d["status"] == "draft"))


@pytest.mark.parametrize("S", [Rest, Mcp])
def test_delete_is_refused_while_a_request_references_the_cohort(bclient, S):
    req, cohort_id = seed(bclient)
    r = S(bclient, A).delete(str(cohort_id))
    assert r.code in (409, None) and "attached to a request" in json.dumps(r.body)
    assert ok(Rest(bclient, A).get(cohort_id))["id"] == str(cohort_id)
    assert sql("SELECT count(*) AS n FROM cohort_revision")[0]["n"] == 1
    other = S(bclient, B).delete(str(cohort_id))   # someone else's cohort is still a plain 404
    assert other.code in (404, None) and "no saved cohort" in json.dumps(other.body)


def test_the_database_refuses_too(bclient):
    _, cohort_id = seed(bclient)
    with pytest.raises(IntegrityError):
        sql("DELETE FROM cohort WHERE id = :id", id=cohort_id)
    with pytest.raises(IntegrityError):
        sql("DELETE FROM cohort_revision WHERE cohort = :id", id=cohort_id)


def test_constraints(bclient):
    req, cohort_id = seed(bclient)
    release = sql("SELECT id FROM release")[0]["id"]
    new_request = ("INSERT INTO request (id, requester, cohort, seq, irb_number, irb_version, purpose, fields, "
                   "identifiers, recipients, storage_location, retention_end, status) VALUES (:id, :who, :c, 1, "
                   ":irb, :v, '', '[]', '[]', '[]', '', :ret, :status)")
    ok_args = dict(who=A, c=cohort_id, irb="TEST-0001", v=1, ret=datetime.date(2027, 6, 1), status="submitted")
    bad = [
        (new_request, ok_args | {"status": "bogus"}),
        (new_request, ok_args | {"irb": None, "v": None}),            # non-draft without an IRB
        (new_request, ok_args | {"ret": None}),                       # non-draft without a retention date
        ("INSERT INTO review (id, request_id, reviewer, checklist, decision, notes) VALUES"
         " (:id, :r, 'x', '{}', 'maybe', '')", {"r": req}),
        ("INSERT INTO irb_document (id, irb_number, version, doc_type, file_ref, sha256, created_by) VALUES"
         " (:id, 'TEST-0001', 1, 'selfie', 'f', :sha, 'x')", {"sha": SHA}),
        ("INSERT INTO irb_document (id, irb_number, version, doc_type, file_ref, sha256, created_by) VALUES"
         " (:id, 'TEST-0001', 1, 'consent_form', 'f', :sha, 'x')", {"sha": "G" * 64}),
        ("INSERT INTO release (id, request_id, file_name, sha256, row_count, fields_released, recipients,"
         " sharepoint_link) VALUES (:id, :r, 'f', 'abc', 1, '[]', '[]', 'l')", {"r": req}),
        ("INSERT INTO release (id, request_id, file_name, sha256, row_count, fields_released, recipients,"
         " sharepoint_link) VALUES (:id, :r, 'f', :sha, -1, '[]', '[]', 'l')", {"r": req, "sha": SHA}),
        ("INSERT INTO release_patient (release_id, research_id) VALUES (:r, '1234567')", {"r": release}),   # an MRN
        ("INSERT INTO release_patient (release_id, research_id) VALUES (:r, 'ABCDEF0123456789')", {"r": release}),
        ("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, hipaa_pathway, approved_population,"
         " status, created_by) VALUES ('TEST-0003', 1, 'p', '2026-01-01', 'w', 'p', 'expired', 'x')", {}),
        ("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, hipaa_pathway, approved_population,"
         " status, created_by) VALUES ('TEST-0003', 0, 'p', '2026-01-01', 'w', 'p', 'active', 'x')", {}),
    ]
    for statement, args in bad:
        with pytest.raises(IntegrityError):
            sql(statement, **({"id": uuid.uuid4()} | args))


def test_no_response_carries_a_study_id(bclient):
    req, _ = seed(bclient)
    seen = []
    for s in (RestReads(bclient, BROKER, True), McpReads(bclient, BROKER, True)):
        for body in (s.mine()[1], s.my(req)[1], s.requests()[1], s.request(req)[1], s.irbs()[1], s.irb("TEST-0001")[1]):
            seen.append(json.dumps(body))
            assert "research_id" not in {k for k, _ in walk(body)}
    text = " ".join(seen)
    assert "research_id" not in text
    assert not any(p in text for p in RESEARCH_IDS)


def test_no_broker_table_holds_a_phi_column(bclient):
    names = {r["column_name"] for r in sql(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name IN ('irb_authorization','irb_document','irb_personnel','request','review','release',"
        "'release_patient')")}
    assert names and not names & DROP


def test_unconfigured_database_is_503(ids, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(authen, "user", lambda request: authen.User("u", "u", True))
    with TestClient(app.app()) as c:
        assert c.get("/api/requests").status_code == 503
        assert c.get("/api/broker/irb").status_code == 503
