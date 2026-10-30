"""Honest-broker records: IRB registry, requests, reviews, releases, read-only over REST and MCP (docs/specs/132-*.md),
and the requester's intake: IRB references, draft, attestation, submit (docs/specs/133-*.md; REST only).

Synthetic #34 mart in a temp dir plus the throwaway Postgres of test_saved (TEST_DATABASE_URL). Seed rows are
inserted with SQL and hold synthetic values only. Never $DATA/raw, the PHI file, the real de-id file or the
real DATABASE_URL.
"""
import asyncio
import datetime
import json
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
import sqlalchemy as sa
from starlette.testclient import TestClient

from test_app import MCP_HEADERS, accepted_yes, ids, mart_file, walk  # noqa: F401  (fixtures)
from test_saved import A, B, COUNTED, START, Mcp, Rest, clean, ok, pg_url, sql  # noqa: F401
from uccc_genomics.deid import DROP
from uccc_genomics_mcp import app, authen, broker, cohort, saved, terms

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
    monkeypatch.setattr(terms, "accepted", accepted_yes)
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
    assert not {"documents", "personnel"} & detail["irb"].keys()   # a requester sees the IRB's status only
    assert "file_ref" not in json.dumps(detail)
    broker = S(bclient, BROKER, True).request(req)[1]["irb"]
    assert [d["doc_type"] for d in broker["documents"]] == ["protocol_excerpt", "approval_letter"]
    assert [p["person_id"] for p in broker["personnel"]] == ["a@example.edu", "b@example.edu"]
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


# --- requester intake (#133) ---------------------------------------------------------------------

class Writes(Surface):
    """The seven requester write calls over REST: (status code, JSON)."""

    def _(self, method, path, body=None):
        r = self.c.request(method, path, json=body, headers=self.headers())
        return r.status_code, r.json()

    def create(self, cohort, seq=1): return self._("POST", "/api/requests", {"cohort": str(cohort), "seq": seq})
    def put(self, id, draft): return self._("PUT", f"/api/requests/{id}", draft)
    def get(self, id): return self._("GET", f"/api/requests/{id}")
    def submit(self, id, text): return self._("POST", f"/api/requests/{id}/submit", {"attestation": text})
    def delete(self, id): return self._("DELETE", f"/api/requests/{id}")
    def lookup(self, q): return self._("GET", "/api/irb", None) if q is None else self._("GET", f"/api/irb?q={q}")
    def register(self, body): return self._("POST", "/api/irb", body)
    def doc(self, n, v, body): return self._("POST", f"/api/irb/{n}/{v}/documents", body)


IRB = {"irb_number": "TEST-0100", "pi": "Dr Example", "approval_date": "2026-01-01", "expiration_date": "2099-01-01",
       "hipaa_pathway": "waiver", "approved_population": "synthetic population"}
DOCS = [{"doc_type": "approval_letter", "title": "Approval letter", "file_ref": "https://example.test/a"},
        {"doc_type": "personnel_list", "title": "Personnel list, amendment 3", "file_ref": "folder/personnel"},
        {"doc_type": "protocol_excerpt", "title": "Protocol excerpt", "file_ref": "folder/excerpt",
         "section_cited": "4.2", "protocol_version": "v2"}]
RETENTION = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
FRESH = ["choose an IRB authorization", "state the purpose", "choose at least one identifier, with a reason",
         "name at least one recipient", "give the storage location", "give a retention end date after today"]


def draft(version=1, **kw):
    return {"irb_number": "TEST-0100", "irb_version": version, "purpose": "synthetic purpose",
            "fields": ["demographics", "diagnosis"], "identifiers": [{"identifier": "mrn", "reason": "synthetic reason"}],
            "recipients": [{"name": "R Example", "email": "R@Example.edu"}], "storage_location": "synthetic share",
            "retention_end": RETENTION} | kw


def started(c, user=A, docs=DOCS):
    """A's new draft on a new saved cohort, IRB TEST-0100 v1 registered by `user` with `docs` referenced.
    Returns (Writes, request id, cohort id)."""
    w = Writes(c, user)
    cohort_id = ok(Rest(c, user).save(START))["id"]
    code, d = w.create(cohort_id)
    assert code == 200
    assert w.register(IRB)[0] == 200
    for doc in docs:
        assert w.doc("TEST-0100", 1, doc)[0] == 200
    return w, d["id"], cohort_id


def attestation_rows():
    return sql("SELECT request_id, attestation_version, text, signed_by, signed_as FROM request_attestation "
               "ORDER BY signed_at, id")


def test_intake_happy_path(bclient):
    w, id, cohort_id = started(bclient)
    code, d = w.get(id)
    assert d["status"] == "draft" and d["missing"] == FRESH and d["attestation"] is None
    assert d["irb"] is None and (d["cohort"], d["seq"]) == (cohort_id, 1)
    code, d = w.put(id, draft())
    assert code == 200 and d["missing"] == [] and d["status"] == "draft"
    assert d["recipients"] == [{"name": "R Example", "email": "r@example.edu"}]
    assert d["irb"] == {"irb_number": "TEST-0100", "version": 1, "status": "active", "expiration_date": "2099-01-01",
                        "doc_types": ["approval_letter", "personnel_list", "protocol_excerpt"], "registered_by_you": True}
    text = d["attestation"]
    for part in ("TEST-0100", "section 4.2", "protocol version v2", "synthetic share", RETENTION):
        assert part in text
    code, d = w.submit(id, text)
    assert code == 200 and d["status"] == "submitted" and d["missing"] == [] and d["attestation"] is None
    assert [(a["attestation_version"], a["text"], a["signed_as"]) for a in d["attestations"]] == \
        [(broker.ATTESTATION_VERSION, text, A)]
    assert attestation_rows() == [{"request_id": uuid.UUID(id), "attestation_version": broker.ATTESTATION_VERSION,
                                   "text": text, "signed_by": A, "signed_as": A}]
    assert w.put(id, draft())[0] == 409
    assert [r["id"] for r in RestReads(bclient, BROKER, True).requests("submitted")[1]["requests"]] == [id]


def test_create_checks_cohort_ownership(bclient):
    cohort_id = ok(Rest(bclient, A).save(START))["id"]
    a, b = Writes(bclient, A), Writes(bclient, B)
    random_id = uuid.uuid4()
    other, nobody = b.create(cohort_id), b.create(random_id)
    assert other[0] == nobody[0] == 404 and "no saved cohort" in json.dumps(other[1])
    assert json.dumps(other[1]).replace(cohort_id, "X") == json.dumps(nobody[1]).replace(str(random_id), "X")
    assert sql("SELECT count(*) AS n FROM request") == [{"n": 0}]
    code, body = a.create(cohort_id, 2)
    assert code == 404 and body["detail"] == "no revision 2"
    for _ in range(broker.MAX_DRAFTS):
        assert a.create(cohort_id)[0] == 200
    code, body = a.create(cohort_id)
    assert code == 409 and "at most 20 draft requests" in body["detail"]
    assert b.create(cohort_id)[0] == 404


@pytest.mark.parametrize("name, change, expected", [
    ("fresh draft", None, FRESH),
    ("suspended", "UPDATE irb_authorization SET status = 'suspended'", ["IRB TEST-0100 version 1 is suspended"]),
    ("closed", "UPDATE irb_authorization SET status = 'closed'", ["IRB TEST-0100 version 1 is closed"]),
    ("expired", "UPDATE irb_authorization SET expiration_date = '2020-01-01'",
     ["IRB TEST-0100 version 1 expired on 2020-01-01"]),
    ("no documents", "DELETE FROM irb_document WHERE doc_type <> 'consent_form'",
     ["add a reference to the IRB approval letter", "add a reference to the approved personnel list",
      "add a reference to the protocol excerpt"]),
    ("no excerpt", "DELETE FROM irb_document WHERE doc_type = 'protocol_excerpt'",
     ["add a reference to the protocol excerpt"]),
])
def test_missing_rules(bclient, name, change, expected):
    w, id, _ = started(bclient)
    if change is None:
        assert w.get(id)[1]["missing"] == expected
        return
    assert w.put(id, draft())[1]["missing"] == []
    sql(change)
    code, d = w.get(id)
    assert d["missing"] == expected and d["attestation"] is None


def test_missing_for_each_blank_field(bclient):
    w, id, _ = started(bclient)
    for kw, text in ((dict(purpose=""), "state the purpose"), (dict(identifiers=[]), FRESH[2]),
                     (dict(recipients=[]), FRESH[3]), (dict(storage_location=""), FRESH[4]),
                     (dict(retention_end=None), FRESH[5]),
                     (dict(retention_end=datetime.date.today().isoformat()), FRESH[5]),
                     (dict(fields=[]), None)):   # fields are optional
        code, d = w.put(id, draft(**kw))
        assert code == 200 and d["missing"] == ([text] if text else []), kw
    assert w.put(id, draft(irb_number=None, irb_version=None))[1]["missing"] == ["choose an IRB authorization"]


def test_put_validation(bclient):
    w, id, _ = started(bclient)
    assert w.put(id, draft(irb_number="NOPE-1")) == (400, {"detail": "no IRB authorization NOPE-1 version 1"})
    assert w.put(id, draft(irb_version=None))[0] == 422                       # half-set pair
    assert w.put(id, draft(irb_number=None))[0] == 422
    assert w.put(id, draft(identifiers=[{"identifier": "mrn", "reason": "a"}, {"identifier": "mrn", "reason": "b"}]))[0] == 422
    assert w.put(id, draft(recipients=[{"name": "A", "email": "a@x.edu"}, {"name": "B", "email": "A@X.EDU"}]))[0] == 422
    assert w.put(id, draft(fields=["age_band"]))[0] == 422
    assert w.put(id, draft(fields=["diagnosis", "diagnosis"]))[0] == 422
    assert w.put(id, draft(recipients=[{"name": "A", "email": "not an email"}]))[0] == 422
    assert w.put(id, draft(identifiers=[{"identifier": "ssn", "reason": "x"}]))[0] == 422
    assert w.put(id, draft(irb_number="../x"))[0] == 422
    assert w.put(id, draft())[0] == 200
    sql("UPDATE request SET status = 'denied'")
    assert w.put(id, draft())[0] == 409


@pytest.mark.parametrize("bad", ["MRN 1234567", "TN12-345678", "tn12-345678", "ORD-123456 and more", "US123456.12"])
def test_free_text_guard(bclient, bad):
    w, id, _ = started(bclient)
    for kw in (dict(purpose=bad), dict(storage_location=bad),
               dict(identifiers=[{"identifier": "mrn", "reason": bad}]),
               dict(recipients=[{"name": bad, "email": "r@example.edu"}])):
        code, body = w.put(id, draft(**kw))
        assert code == 422 and "7 or more digits" in json.dumps(body), kw
    assert w.register(IRB | {"irb_number": "TEST-0101", "pi": bad})[0] == 422
    assert w.doc("TEST-0100", 1, DOCS[0] | {"title": bad})[0] == 422
    assert w.put(id, draft(purpose="grant 123456 and 12 345 6789"))[0] == 200     # six digits, or spaced, pass


def test_submit_refusals(bclient):
    w, id, _ = started(bclient)
    code, body = w.submit(id, "x")
    assert code == 400 and body["detail"] == "can't submit yet: " + "; ".join(FRESH)
    text = w.put(id, draft())[1]["attestation"]
    code, body = w.submit(id, text[:-1] + "!")
    assert code == 409 and "read it again" in body["detail"]
    assert w.submit(id, text.replace("TEST-0100", "TEST-0101"))[0] == 409
    assert attestation_rows() == [] and w.get(id)[1]["status"] == "draft"
    assert w.submit(id, text)[0] == 200
    code, body = w.submit(id, text)
    assert code == 409 and "is submitted" in body["detail"] and len(attestation_rows()) == 1


def test_returned_request_can_be_resubmitted(bclient):
    w, id, _ = started(bclient)
    first = w.put(id, draft())[1]["attestation"]
    assert w.submit(id, first)[0] == 200
    sql("UPDATE request SET status = 'returned'")
    code, d = w.get(id)
    assert d["status"] == "returned" and d["missing"] == [] and d["attestation"] == first
    assert w.put(id, draft(irb_number=None, irb_version=None))[0] == 400    # the table keeps a returned request's IRB
    assert w.put(id, draft(retention_end=None))[0] == 400
    code, d = w.put(id, draft(storage_location="another share"))
    assert code == 200 and d["status"] == "returned" and "another share" in d["attestation"]
    code, d = w.submit(id, d["attestation"])
    assert code == 200 and d["status"] == "submitted"
    assert [r["signed_by"] for r in attestation_rows()] == [A, A] and len(d["attestations"]) == 2


def test_delete_draft_only(bclient):
    w, id, cohort_id = started(bclient)
    assert Rest(bclient, A).delete(cohort_id).code == 409
    code, body = w.delete(id)
    assert (code, body) == (200, {"id": id}) and w.get(id)[0] == 404
    assert Rest(bclient, A).delete(cohort_id).code == 200
    w, id, _ = started(bclient)
    assert w.submit(id, w.put(id, draft())[1]["attestation"])[0] == 200
    code, body = w.delete(id)
    assert code == 409 and "was submitted" in body["detail"] and w.get(id)[0] == 200


def test_other_users_request_is_missing(bclient):
    w, id, _ = started(bclient)
    b, nobody = Writes(bclient, B), uuid.uuid4()
    for call in (lambda s, i: s.get(i), lambda s, i: s.put(i, draft()), lambda s, i: s.submit(i, "x"),
                 lambda s, i: s.delete(i)):
        mine, missing = call(b, id), call(b, nobody)
        assert mine[0] == missing[0] == 404 and "no request" in json.dumps(mine[1])
        assert json.dumps(mine[1]).replace(id, "X") == json.dumps(missing[1]).replace(str(nobody), "X")
    assert w.get(id)[0] == 200 and sql("SELECT count(*) AS n FROM request") == [{"n": 1}]


def test_irb_lookup_shape_and_escape(bclient):
    w, _, _ = started(bclient)
    assert w.register(IRB | {"expiration_date": None})[0] == 200       # version 2, no documents
    b = Writes(bclient, B)
    assert b.register(IRB | {"irb_number": "T%X-1"})[0] == 422          # the pattern refuses %, and so does a number
    sql("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, hipaa_pathway, approved_population,"
        " status, created_by) VALUES ('T%X-1', 1, 'p', '2026-01-01', 'w', 'p', 'active', 'x')")   # but seed one anyway
    assert b.register(IRB | {"irb_number": "OTHER-1"})[0] == 200
    code, body = b.lookup("TEST")
    assert code == 200 and body == {"authorizations": [
        {"irb_number": "TEST-0100", "version": 2, "status": "active", "expiration_date": None, "doc_types": [],
         "registered_by_you": False}]}
    assert {a["irb_number"] for a in b.lookup("t")[1]["authorizations"]} == {"TEST-0100", "T%X-1"}   # case-insensitive
    assert [a["irb_number"] for a in b.lookup("T%25")[1]["authorizations"]] == ["T%X-1"]             # the % is literal
    assert b.lookup("T_")[1] == {"authorizations": []}
    assert b.lookup("")[0] == 422 and b.lookup("x" * 65)[0] == 422 and b.lookup(None)[0] == 422
    text = json.dumps(b.lookup("TEST")[1]) + json.dumps(b.lookup("T%25")[1])
    for key in ("pi", "file_ref", "approved_population", "personnel", "hipaa_pathway", "created_by"):
        assert f'"{key}"' not in text
    assert "Dr Example" not in text


def test_register_irb_versions_and_cap(bclient):
    a, b = Writes(bclient, A), Writes(bclient, B)
    assert a.register(IRB) == (200, {"irb_number": "TEST-0100", "version": 1, "status": "active",
                                     "expiration_date": "2099-01-01", "doc_types": [], "registered_by_you": True})
    code, body = b.register(IRB)
    assert code == 200 and body["version"] == 2 and body["registered_by_you"] is True
    assert a.lookup("TEST")[1]["authorizations"][0]["registered_by_you"] is False       # latest is B's
    assert a.register(IRB | {"expiration_date": "2025-01-01"})[0] == 422                 # before approval
    assert a.register(IRB | {"irb_number": " TEST-0100 "})[1]["version"] == 3             # stripped
    code, body = a.register(IRB | {"irb_number": "test-0100"})                            # upper-cased, never a second number
    assert code == 200 and body["irb_number"] == "TEST-0100" and body["version"] == 4
    assert sql("SELECT status, created_by FROM irb_authorization WHERE version = 2") == [
        {"status": "active", "created_by": B}]
    sql("INSERT INTO irb_authorization (irb_number, version, pi, approval_date, hipaa_pathway, approved_population,"
        " status, created_by) SELECT 'BULK-' || g, 1, 'p', '2026-01-01', 'w', 'p', 'active', :u "
        "FROM generate_series(1, :n) g", u=B, n=broker.MAX_IRB_VERSIONS - 1)
    code, body = b.register(IRB | {"irb_number": "TEST-0200"})
    assert code == 409 and "at most 50 IRB versions" in body["detail"]


def test_document_references_by_creator_only(bclient):
    w, _, _ = started(bclient, docs=[])
    b = Writes(bclient, B)
    code, body = w.doc("TEST-0100", 1, DOCS[0])
    assert code == 200 and body["doc_types"] == ["approval_letter"] and body["registered_by_you"] is True
    assert w.doc("TEST-0100", 1, DOCS[0])[1]["doc_types"] == ["approval_letter"]          # a second reference, one type
    code, body = b.doc("TEST-0100", 1, DOCS[1])
    assert code == 409 and "registered by someone else" in body["detail"]
    assert b.doc("TEST-0100", 9, DOCS[1])[0] == 404 and b.doc("NOPE-1", 1, DOCS[1])[0] == 404
    assert w.doc("TEST-0100", 1, {k: v for k, v in DOCS[2].items() if k != "section_cited"})[0] == 422
    assert w.doc("TEST-0100", 1, {k: v for k, v in DOCS[2].items() if k != "protocol_version"})[0] == 422
    assert w.doc("TEST-0100", 1, DOCS[0] | {"doc_type": "selfie"})[0] == 422
    assert w.doc("../x", 1, DOCS[0])[0] in (404, 422) and w.doc("TEST-0100", 0, DOCS[0])[0] == 422
    assert w.doc("TEST-0100", 1, DOCS[2])[0] == 200
    rows = sql("SELECT title, file_ref, sha256, created_by, section_cited FROM irb_document ORDER BY created_at, id")
    assert rows[0] == {"title": "Approval letter", "file_ref": "https://example.test/a", "sha256": None,
                       "created_by": A, "section_cited": None}
    assert rows[-1]["section_cited"] == "4.2" and len(rows) == 3
    for _ in range(broker.MAX_DOCUMENTS):
        code, body = w.doc("TEST-0100", 1, DOCS[0])
        if code == 409:
            break
    assert code == 409 and "at most 20 document references" in body["detail"]


def test_attestation_uses_the_newest_excerpt(bclient):
    w, id, _ = started(bclient)
    w.doc("TEST-0100", 1, DOCS[2] | {"title": "Newer", "section_cited": "9.9", "protocol_version": "v3"})
    text = w.put(id, draft())[1]["attestation"]
    assert "section 9.9 of protocol version v3" in text


def test_requester_irb_is_status_only(bclient):
    req, _ = seed(bclient)
    assert set(RestReads(bclient, A).my(req)[1]["irb"]) == {"irb_number", "version", "status", "expiration_date",
                                                           "doc_types", "registered_by_you"}
    assert set(McpReads(bclient, A).my(req)[1]["irb"]) == set(RestReads(bclient, A).my(req)[1]["irb"])
    assert RestReads(bclient, A).my(req)[1]["irb"]["doc_types"] == ["approval_letter", "protocol_excerpt"]
    assert "documents" in RestReads(bclient, BROKER, True).request(req)[1]["irb"]


def test_new_routes_never_carry_a_study_id(bclient):
    req, _ = seed(bclient)
    w, id, _ = started(bclient)
    bodies = [w.get(id)[1], w.put(id, draft())[1], w.lookup("TEST")[1], w.register(IRB | {"irb_number": "TEST-0300"})[1],
              w.doc("TEST-0300", 1, DOCS[0])[1], w.create(sql("SELECT cohort FROM request LIMIT 1")[0]["cohort"])[1]]
    bodies.append(w.submit(id, bodies[1]["attestation"])[1])
    text = json.dumps(bodies)
    assert "research_id" not in text and not any(p in text for p in RESEARCH_IDS)
    for body in bodies:
        assert "research_id" not in {k for k, _ in walk(body)}


def test_delete_and_create_serialize_on_the_cohort_row(clean):
    insert = ("INSERT INTO request (id, requester, cohort, seq, purpose, fields, identifiers, recipients, "
              "storage_location, status) VALUES (:id, :who, :c, 1, '', '[]', '[]', '[]', '', 'draft')")
    lock = sa.text("SELECT id FROM cohort WHERE id = :id FOR UPDATE")

    async def go():
        saved.start(saved.database_url())
        holder_engine = create_async_engine(saved.database_url())
        try:
            c = await saved.create(A, cohort.parse(START), snapshot_id=None)
            async with holder_engine.connect() as holder:       # a request appears while delete waits
                await holder.execute(lock, {"id": c.id})
                task = asyncio.create_task(saved.delete(A, c.id))
                await asyncio.sleep(0.3)
                assert not task.done()
                await holder.execute(sa.text(insert), {"id": uuid.uuid4(), "who": A, "c": c.id})
                await holder.commit()
                with pytest.raises(saved.Conflict):
                    await task
            c2 = await saved.create(A, cohort.parse(START), snapshot_id=None)
            async with holder_engine.connect() as holder:       # the cohort goes while create waits
                await holder.execute(lock, {"id": c2.id})
                task = asyncio.create_task(broker.create_request(A, broker.RequestCreate(cohort=c2.id, seq=1)))
                await asyncio.sleep(0.3)
                assert not task.done()
                await holder.execute(sa.text("DELETE FROM cohort WHERE id = :id"), {"id": c2.id})   # revisions cascade
                await holder.commit()
                with pytest.raises(saved.NotFound):
                    await task
        finally:
            await holder_engine.dispose()
            await saved.stop()

    asyncio.run(go())
