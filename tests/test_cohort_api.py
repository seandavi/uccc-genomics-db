"""Cohort API: floor, validation, auth and counts on a synthetic DB; one check against the real DB.

The synthetic DB has only the columns the API reads. Known answers:
  - 12 colorectal patients (Caris tissue, female, 60, 2023) with TP53 p.R175H; patient c0 has a
    second R175H report in 2024, so TP53 R175H colorectal is 12 patients, 13 reports.
  - 8 pancreatic patients (FMI, 2024), 3 with TP53 R175H (likely pathogenic tier, merged with the
    pathogenic tier): a small cell everywhere it appears.
  - 20 melanoma patients (FMI, male, 2022), 6 with BRAF V600E, 6 with a KRAS G12C VUS, 6 with an
    unclassified NRAS Q61K.
  - 6 of the colorectal patients also carry a benign APC I1307K, which is never an alteration.
  - 2 thymic patients: below the floor, so not in the disease vocabulary.
"""
import json
import os
from urllib.parse import urlencode

import duckdb
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from uccc_genomics.config import DEID_DB
from conftest import deid_lacks_tier
from uccc_genomics_mcp import authen, cohort_api, server


def build(path):
    con = duckdb.connect(path)
    con.execute("""
        CREATE SCHEMA unified; CREATE SCHEMA caris;
        CREATE TABLE unified.report (vendor VARCHAR, report_id VARCHAR, research_id VARCHAR, disease_text VARCHAR,
                                     organ_system VARCHAR, gender VARCHAR, assay_class VARCHAR, collected_on DATE);
        CREATE TABLE unified.variant (vendor VARCHAR, report_id VARCHAR, gene VARCHAR, hgvs_p VARCHAR, tier VARCHAR);
        CREATE TABLE unified.cna (vendor VARCHAR, report_id VARCHAR, gene VARCHAR, cn_type VARCHAR);
        CREATE TABLE unified.fusion (vendor VARCHAR, report_id VARCHAR, gene1 VARCHAR, gene2 VARCHAR);
        CREATE TABLE caris.specimen (case_id VARCHAR, specimen_kind VARCHAR, age_at_collection INT);""")
    rep, var = [], []
    for i in range(12):
        rep.append(("caris", f"c{i}", f"c{i}", "Colorectal Adenocarcinoma", "Bowel", "Female", "tissue", "2023-06-01"))
        var.append(("caris", f"c{i}", "TP53", "p.R175H", "pathogenic"))
        if i < 6:
            var.append(("caris", f"c{i}", "APC", "p.I1307K", "likely_benign_or_benign"))
        con.execute("INSERT INTO caris.specimen VALUES (?, 'tumor', 60)", [f"c{i}"])
    rep.append(("caris", "c0b", "c0", "Colorectal Adenocarcinoma", "Bowel", "Female", "tissue", "2024-06-01"))
    var.append(("caris", "c0b", "TP53", "R175H", "pathogenic"))
    con.execute("INSERT INTO caris.specimen VALUES ('c0b', 'tumor', 61)")
    for i in range(8):
        rep.append(("fmi", f"p{i}", f"p{i}", "Pancreatic Adenocarcinoma", "Pancreas", "female", "tissue", "2024-06-01"))
        if i < 3:
            var.append(("fmi", f"p{i}", "TP53", "R175H", "likely_pathogenic"))
    for i in range(20):
        rep.append(("fmi", f"m{i}", f"m{i}", "Melanoma", "Skin", "Male", "tissue", "2022-06-01"))
        if i < 6:
            var.append(("fmi", f"m{i}", "BRAF", "V600E", "pathogenic"))
        elif i < 12:
            var.append(("fmi", f"m{i}", "KRAS", "G12C", "vus"))
        elif i < 18:
            var.append(("fmi", f"m{i}", "NRAS", "Q61K", "unclassified"))
    for i in range(2):
        rep.append(("fmi", f"t{i}", f"t{i}", "Thymic Tumor", "Thymus", "male", "tissue", "2022-06-01"))
    con.executemany("INSERT INTO unified.report VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rep)
    con.executemany("INSERT INTO unified.variant VALUES (?, ?, ?, ?, ?)", var)
    con.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "cohort.duckdb")
    build(path)
    monkeypatch.setattr(cohort_api, "DEID_DB", path)
    monkeypatch.setattr(cohort_api, "get_db", lambda: server.harden(duckdb.connect(path, read_only=True)))
    monkeypatch.setattr(cohort_api, "_vocab", {"mtime": None})
    return TestClient(cohort_api.app())


def get(client, **params):
    return client.get("/api/cohort?" + urlencode(params, doseq=True))


def walk(x):
    """Every (key, value) pair anywhere in a response."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


QUERIES = [{}, {"gene": "TP53"}, {"gene": "TP53", "aa": "R175H"}, {"disease": "Pancreatic Adenocarcinoma"},
           {"gene": "KRAS", "alt_class": "vus"}, {"gene": "NRAS", "alt_class": "unclassified"},
           {"gene": ["TP53", "BRAF"]}, {"sex": "male"}, {"year_from": 2024}]


@pytest.mark.parametrize("params", QUERIES)
def test_no_small_numbers_and_no_ids(client, params):
    r = get(client, **params)
    assert r.status_code == 200
    for k, v in walk(r.json()):
        assert k not in ("research_id", "report_id")
        assert not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v < 5), (k, v)


def test_counts_patients_not_reports(client):
    body = get(client, gene="TP53", aa="R175H", disease="Colorectal Adenocarcinoma").json()
    assert (body["patients"], body["reports"], body["tested"]) == (12, 13, 12)
    # c0's 2024 report does not move them out of 2023, their first qualifying year.
    assert body["by_year"] == [{"year": 2023, "patients": 12}]
    assert body["by_age"] == [{"age": "50-64", "patients": 12}]


def test_prevalence_denominator_and_or_within_a_parameter(client):
    body = get(client, gene="TP53", aa="R175H", organ=["Bowel", "Pancreas"]).json()
    assert (body["patients"], body["tested"]) == (15, 20)
    body = get(client, gene="BRAF", organ=["Skin", "Bowel"]).json()
    assert (body["patients"], body["tested"]) == (6, 32)


def test_secondary_suppression(client):
    # 2023: 12, 2024: 3. With the total shown, a lone hidden 3 would be 15 - 12; so 12 goes too.
    body = get(client, gene="TP53", aa="R175H").json()
    assert body["patients"] == 15
    assert body["by_year"] == [{"year": 2023, "patients": None}, {"year": 2024, "patients": None}]
    assert {d["disease"]: d["patients"] for d in body["by_disease"]} == {
        "Colorectal Adenocarcinoma": None, "Pancreatic Adenocarcinoma": None}


def test_whole_cohort_rule(client):
    body = get(client, gene="TP53", disease="Pancreatic Adenocarcinoma").json()
    assert body["patients"] is None and body["tested"] == 8
    assert all(body[k] == [] for k in body if k.startswith("by_"))


def test_vus_is_excluded_unless_asked(client):
    assert get(client, gene="KRAS").json()["patients"] == 0
    assert get(client, gene="KRAS", alt_class="vus").json()["patients"] == 6


def test_unclassified_is_opt_in(client):
    assert get(client, gene="NRAS").json()["patients"] == 0
    assert get(client, gene="NRAS", alt_class="unclassified").json()["patients"] == 6


def test_benign_is_never_an_alteration(client):
    r = get(client, gene="APC")
    assert r.status_code == 400 and "gene" in r.json()["error"]


def test_vocabularies_are_floored(client):
    opts = client.get("/api/options").json()
    assert "Thymic Tumor" not in opts["disease"] and "Melanoma" in opts["disease"]
    assert opts["aa"] == {"TP53": ["R175H"], "BRAF": ["V600E"], "KRAS": ["G12C"], "NRAS": ["Q61K"]}
    assert opts["alt_class"] == ["pathogenic", "vus", "unclassified", "amplification", "loss", "fusion"]
    assert (opts["year_min"], opts["year_max"]) == (2022, 2024)


@pytest.mark.parametrize("params, name", [
    ({"foo": "1"}, "foo"),
    ({"disease": "Thymic Tumor"}, "disease"),
    ({"disease": "x' OR 1=1 --"}, "disease"),
    ({"aa": "R175H"}, "aa"),
    ({"gene": ["TP53", "BRAF"], "aa": "R175H"}, "aa"),
    ({"gene": "BRAF", "aa": "R175H"}, "aa"),
    ({"alt_class": "vus"}, "alt_class"),
    ({"year_from": "1990"}, "year_from"),
    ({"year_to": "2024; DROP"}, "year_to"),
])
def test_bad_requests_name_the_parameter(client, params, name):
    r = get(client, **params)
    assert r.status_code == 400 and name in r.json()["error"]


def test_health(client):
    assert client.get("/api/health").json() == {"status": "Healthy", "reports": 43}


def test_access_jwt(client, monkeypatch, capsys):
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

    assert client.get("/api/cohort").status_code == 401
    assert client.get("/api/options").status_code == 401
    assert client.get("/api/cohort", headers={"cf-access-jwt-assertion": "garbage"}).status_code == 401
    assert client.get("/api/cohort", headers={"cf-access-jwt-assertion": token(aud="other")}).status_code == 401
    assert client.get("/api/cohort", headers={"cf-access-jwt-assertion": token(iss="https://evil")}).status_code == 401
    assert client.get("/api/health").status_code == 200  # the uptime probe has no token
    assert client.get("/api/options", cookies={"CF_Authorization": token()}).status_code == 200
    capsys.readouterr()
    r = client.get("/api/cohort?gene=BRAF", headers={"cf-access-jwt-assertion": token()})
    assert r.status_code == 200
    log = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert log["email"] == "a@b.edu" and log["params"]["gene"] == ["BRAF"] and log["patients"] == 6


def test_password(client, monkeypatch, capsys):
    monkeypatch.setenv("APP_USER", "sean")
    monkeypatch.setenv("APP_PASSWORD_HASH", authen.hash_password("s3cret"))
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    authen.configure("password")

    r = client.get("/api/options")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/options", auth=("sean", "wrong")).status_code == 401
    assert client.get("/api/options", auth=("other", "s3cret")).status_code == 401
    assert client.get("/api/options", headers={"authorization": "Basic !!!"}).status_code == 401
    assert client.get("/api/health").status_code == 200
    capsys.readouterr()
    assert client.get("/api/cohort?gene=BRAF", auth=("sean", "s3cret")).status_code == 200
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["email"] == "sean"


def test_password_needs_env(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD_HASH", raising=False)
    monkeypatch.setattr(authen, "AUTH", dict(authen.AUTH))
    with pytest.raises(SystemExit, match="APP_PASSWORD_HASH"):
        authen.configure("password")


@pytest.mark.skipif(not os.path.exists(DEID_DB), reason=f"no {DEID_DB} on this host")
@pytest.mark.skipif(deid_lacks_tier(), reason="real de-id file predates unified.variant.tier; rebuild pending")
def test_real_db_matches_hand_written_sql():
    """TP53 R175H in GI solid tumors, the question that prompted the tool, against SQL written independently."""
    gi = ["Bowel", "Pancreas", "Esophagus/Stomach", "Biliary Tract", "Liver"]
    cohort_api._vocab["mtime"] = None
    body = get(TestClient(cohort_api.app()), gene="TP53", aa="R175H", organ=gi).json()
    con = server.get_db()
    want = con.execute("""
        WITH r AS (SELECT * FROM unified.report WHERE list_contains(?, organ_system)),
        hit AS (SELECT DISTINCT research_id FROM unified.variant
                WHERE gene = 'TP53' AND regexp_replace(hgvs_p, '^p\\.', '') = 'R175H' AND tier IN ('pathogenic', 'likely_pathogenic'))
        SELECT count(DISTINCT research_id) FILTER (research_id IN (SELECT * FROM hit)), count(DISTINCT research_id) FROM r""",
                       [gi]).fetchone()
    con.close()
    assert (body["patients"], body["tested"]) == want
