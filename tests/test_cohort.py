"""Cohort module: definition, operations, cohort_id, vocabulary, compile and suppression.

The synthetic mart (`cohort_db`) has #33's `mart.report` / `mart.fact` columns. Every value is
invented; gene symbols, OncoTree codes and marker names are public vocabulary. Known answers per
group (patients are `<prefix><i>`, one report `<pid>r` each unless noted):
  NSCLC n0-n24   KRAS G12C on 9 patients (n10 also has a liquid report), a VUS on n16, ALK and RET fusions
  COADREAD b0-b19  MSI, TMB, ages, metastatic liver site; PIK3CA, RET, IDH1 mutations
  MEL m0-m9      TMB, FDA-flagged therapy
  BRCA br0-br14  HER2 and ER IHC, ERBB2 amplification, PIK3CA, Caris level 1
  OV ov0-ov9     BRCA1, LOH, TACSTD2 percentile
  STAD st0-st19  CLDN18 and PD-L1 IHC, ERBB2 amplification
  PAAD pa0-pa14  KRAS G12D, WTS, purity, liver metastases
  CHOL ch0-ch14  TP53, CDKN2A, IDH1; the trailing year is incomplete
  THYM t0-t1     below the floor
"""
import json
import os

import duckdb
import pytest

from conftest import deid_lacks_mart
from uccc_genomics.config import DEID_DB
from uccc_genomics_mcp import server
from uccc_genomics_mcp.cohort import (CUT_POINTS, MIN_CELL, Definition, DefinitionError, apply,
                                      cohort_id, count, data_notes, json_schema, operation_json_schema,
                                      parse, pivot, vocabulary)
from uccc_genomics_mcp.cohort import queries, suppress
from uccc_genomics_mcp.cohort.compile import compile, compile_pivot
from uccc_genomics_mcp.cohort.definition import Pivot
from uccc_genomics_mcp.cohort.suppress import _funnel, _line, floor


# --- synthetic mart ------------------------------------------------------------------------------

def age_band(age):
    if age is None:
        return "unknown"
    return "<50" if age < 50 else "50-64" if age < 65 else "65-74" if age < 75 else "75+"


class Mart:
    def __init__(self):
        self.reports, self.facts = [], []

    def report(self, pid, rid, oncotree, organ, vendor, year, *, age=None, sex="female", assay_class="tissue",
               complete=True, wts=False, site_type=None, site=None, purity=None):
        self.reports.append((pid, vendor, rid, year, complete, sex, age, age_band(age), oncotree, organ, oncotree,
                             assay_class, "synthetic", purity, site_type, site, wts))
        if site_type:
            self.fact(rid, "specimen", "site_type", val=site_type)
        if site:
            self.fact(rid, "specimen", "site", val=site)
        if purity is not None:
            self.fact(rid, "specimen", "purity", num=purity, unit="%")

    def fact(self, rid, kind, key, sub=None, val=None, num=None, unit=None, tier=None):
        pid, vendor = next((r[0], r[1]) for r in self.reports if r[2] == rid)
        self.facts.append((pid, vendor, rid, kind, key, sub, val, num, unit, tier))

    def mutation(self, rid, gene, aa, tier="pathogenic"):
        self.fact(rid, "alteration", gene, "mutation", aa, tier=tier)

    def alteration(self, rid, gene, sub, val=None):
        self.fact(rid, "alteration", gene, sub, val)


def build_mart() -> Mart:
    m = Mart()
    rng = lambda prefix, lo, hi: [f"{prefix}{i}" for i in range(lo, hi)]
    for i in range(25):   # NSCLC
        m.report(f"n{i}", f"n{i}r", "NSCLC", "Lung", "caris", 2022 if i < 10 else 2024, age=60)
    m.report("n10", "n10b", "NSCLC", "Lung", "caris", 2023, assay_class="liquid")
    for pid in ["n0", "n1", "n2", "n10", *rng("n", 11, 16)]:
        m.mutation(f"{pid}r", "KRAS", "G12C")
    m.mutation("n10b", "KRAS", "G12C")
    m.mutation("n16r", "KRAS", "G12C", tier="vus")
    for pid in rng("n", 3, 9):
        m.alteration(f"{pid}r", "ALK", "fusion", "EML4")
        m.alteration(f"{pid}r", "EML4", "fusion", "ALK")
    for pid in ("n17", "n18"):
        m.alteration(f"{pid}r", "RET", "fusion", "KIF5B")
        m.alteration(f"{pid}r", "KIF5B", "fusion", "RET")

    for i in range(20):   # COADREAD
        caris = i < 12
        m.report(f"b{i}", f"b{i}r", "COADREAD", "Bowel", "caris" if caris else "fmi", 2023,
                 age=(40 if i < 6 else 70) if caris else None,
                 site_type="metastatic" if i < 6 else None, site="liver" if i < 6 else None)
        m.fact(f"b{i}r", "biomarker", "MSI", val="high" if i < 5 else "stable")
        high = i in (0, 1, 2, 5, 6)
        m.fact(f"b{i}r", "biomarker", "TMB", val="high" if high else "low", num=12.0 if high else 3.0, unit="mut/Mb")
        if 7 <= i < 10:
            m.mutation(f"b{i}r", "PIK3CA", "E545K")
        if 10 <= i < 13:
            m.mutation(f"b{i}r", "RET", "M918T")
        if 13 <= i < 16:
            m.mutation(f"b{i}r", "IDH1", "R132C")

    for i in range(10):   # MEL
        m.report(f"m{i}", f"m{i}r", "MEL", "Skin", "fmi", 2022, sex="male")
        m.fact(f"m{i}r", "biomarker", "TMB", val="high" if i < 8 else "low", num=20.0 if i < 8 else 4.0, unit="mut/Mb")
        m.fact(f"m{i}r", "biomarker", "MSI", val="stable")
        if i < 6:
            m.fact(f"m{i}r", "actionability", "fmi_fda_any_indication", "BRAF", "dabrafenib")

    for i in range(15):   # BRCA
        m.report(f"br{i}", f"br{i}r", "BRCA", "Breast", "caris", 2024, age=55,
                 site_type="metastatic" if i < 2 else None, site="liver" if i < 2 else None)
        her2 = "her2-low" if i < 5 else "her2-ultralow" if i < 10 else "positive" if i < 12 else None
        if her2:
            m.fact(f"br{i}r", "ihc", "ERBB2 (Her2/Neu)", "4b5", her2, 15.0 if i < 5 else None,
                   "% stained" if i < 5 else None)
        if i in (10, 11):
            m.alteration(f"br{i}r", "ERBB2", "amplification")
            m.mutation(f"br{i}r", "PIK3CA", "E545K")
        m.fact(f"br{i}r", "ihc", "ER", "sp1", "positive" if i < 10 else "negative")
        if i < 5:
            m.mutation(f"br{i}r", "PIK3CA", "H1047R")
        if i in (0, 8, 9, 10, 11):
            m.fact(f"br{i}r", "actionability", "caris_level1", "ERBB2", "trastuzumab")

    for i in range(10):   # OV
        m.report(f"ov{i}", f"ov{i}r", "OV", "Ovary", "caris", 2023, wts=True)
        if i < 5:
            m.mutation(f"ov{i}r", "BRCA1", "E1836K")
        high = 2 <= i < 8
        m.fact(f"ov{i}r", "biomarker", "LOH", val="high" if high else "low", num=20.0 if high else 5.0, unit="%")
        m.fact(f"ov{i}r", "expression", "TACSTD2", num=80.0 if i < 5 else 40.0, unit="percentile")

    for i in range(20):   # STAD
        m.report(f"st{i}", f"st{i}r", "STAD", "Esophagus/Stomach", "caris", 2024)
        m.fact(f"st{i}r", "ihc", "CLDN18", "43-14a", "positive" if i < 10 else "negative")
        pos = i < 5 or 10 <= i < 15
        m.fact(f"st{i}r", "ihc", "PD-L1", "22c3", "positive" if pos else "negative", 15.0 if pos else 0.0, "CPS")
        if i < 5:
            m.alteration(f"st{i}r", "ERBB2", "amplification")

    for i in range(15):   # PAAD
        m.report(f"pa{i}", f"pa{i}r", "PAAD", "Pancreas", "caris", 2023, wts=i < 5, purity=40 if i < 5 else 20,
                 site_type="metastatic" if i < 5 else None, site="liver" if i < 5 else None)
        if i < 10:
            m.mutation(f"pa{i}r", "KRAS", "G12D")

    for i in range(15):   # CHOL
        m.report(f"ch{i}", f"ch{i}r", "CHOL", "Biliary Tract", "fmi", 2025, complete=False)
        if i < 6:
            m.mutation(f"ch{i}r", "TP53", "R273H")
        if i < 7:
            m.alteration(f"ch{i}r", "CDKN2A", "loss")
        if i in (7, 8):
            m.mutation(f"ch{i}r", "IDH1", "R132C")

    for i in range(2):   # THYM
        m.report(f"t{i}", f"t{i}r", "THYM", "Thymus", "fmi", 2022, sex="male")
    return m


def write_mart(path, m):
    con = duckdb.connect(path)
    con.execute("""
        CREATE SCHEMA mart;
        CREATE TABLE mart.report (research_id VARCHAR, vendor VARCHAR, report_id VARCHAR, year INTEGER,
          year_complete BOOLEAN, sex VARCHAR, age INTEGER, age_band VARCHAR, oncotree VARCHAR, organ VARCHAR,
          disease VARCHAR, assay_class VARCHAR, assay_name VARCHAR, purity DOUBLE, site_type VARCHAR, site VARCHAR,
          has_wts BOOLEAN);
        CREATE TABLE mart.fact (research_id VARCHAR, vendor VARCHAR, report_id VARCHAR, kind VARCHAR, key VARCHAR,
          sub VARCHAR, val VARCHAR, num DOUBLE, unit VARCHAR, tier VARCHAR);""")
    con.executemany("INSERT INTO mart.report VALUES (" + ", ".join("?" * 17) + ")", m.reports)
    con.executemany("INSERT INTO mart.fact VALUES (" + ", ".join("?" * 10) + ")", m.facts)
    con.close()


@pytest.fixture(scope="module")
def mart_file(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("cohort") / "cohort.duckdb")
    m = build_mart()
    write_mart(path, m)
    return path, m


@pytest.fixture
def cohort_db(mart_file, monkeypatch):
    path, m = mart_file
    return use_mart(path, m, monkeypatch)


def use_mart(path, m, monkeypatch):
    monkeypatch.setattr(queries, "get_db", lambda: server.harden(duckdb.connect(path, read_only=True)))
    monkeypatch.setattr(queries, "DEID_DB", path)
    monkeypatch.setattr(queries, "_vocab", {"mtime": None, "v": None})
    monkeypatch.setattr(suppress, "ROUND", 1)
    return {"ids": {r[0] for r in m.reports} | {r[2] for r in m.reports}, "reports": len(m.reports),
            "patients": len({r[0] for r in m.reports})}


# --- definition helpers ---------------------------------------------------------------------------

def alt(cid, gene, **kw):
    return {"id": cid, "kind": "alteration", "gene": gene, **kw}


def ihc(cid, marker, **kw):
    return {"id": cid, "kind": "ihc", "marker": marker, **kw}


def defn(criteria=(), **kw):
    return parse({"criteria": list(criteria), **kw})


def pop(*oncotree, **kw):
    return {"oncotree": list(oncotree), **kw}


def steps(result):
    return [s.patients for s in result.funnel]


def cells(result, dim):
    return {c.value: (c.patients, c.denominator) for c in result.breakdowns[dim]}


def pcells(result):
    return {(c.row, c.col): c.patients for c in result.cells}


def margins(items):
    return {m.value: m.patients for m in items}


# --- questions -------------------------------------------------------------------------------------

def test_mart_totals(cohort_db):
    assert (cohort_db["patients"], cohort_db["reports"]) == (132, 133)
    assert count(defn()).patients == 132


def test_question_1(cohort_db):
    r = count(defn([alt("c1", ["KRAS"], aa=["G12C"])], population=pop("NSCLC", years=[2023, 2025])))
    assert steps(r) == [15, 6] and r.patients == 6 and r.denominator == 15 and r.reports == 7
    # 2023 is 1 patient, so the line rule hides 2024's 5 too.
    assert [(y.year, y.patients, y.complete) for y in r.by_year] == [(2023, None, True), (2024, None, True)]
    r = count(defn([alt("c1", ["KRAS"], aa=["G12C"])], population=pop("NSCLC")))   # the n16 VUS is not counted
    assert steps(r) == [25, 9]
    assert [(y.year, y.patients) for y in r.by_year] == [(2022, None), (2023, None), (2024, 5)]


def test_question_2(cohort_db):
    r = pivot(defn(pivot={"rows": "oncotree", "cols": "year"}))
    assert r.patients == 132
    shown = {k: v for k, v in pcells(r).items() if v is not None}
    assert shown == {("BRCA", "2024"): 15, ("CHOL", "2025"): 15, ("COADREAD", "2023"): 20, ("NSCLC", "2024"): 15,
                     ("PAAD", "2023"): 15, ("STAD", "2024"): 20}
    hidden = {k for k, v in pcells(r).items() if v is None}
    assert hidden == {("MEL", "2022"), ("NSCLC", "2022"), ("NSCLC", "2023"), ("OV", "2023"), ("THYM", "2022")}
    rows = margins(r.row_totals)
    assert {k for k, v in rows.items() if v is None} == {"MEL", "OV", "THYM"} and rows["NSCLC"] == 25
    assert margins(r.col_totals) == {"2022": 22, "2023": 46, "2024": 50, "2025": 15}


def test_question_3(cohort_db):
    r = count(defn(population=pop("COADREAD", age_band=["<50"])))
    assert r.patients == 6 and any("Age is known" in n for n in r.notes)
    r = count(defn(population=pop("COADREAD"), breakdown=["age_band"]))
    assert cells(r, "age_band") == {"unknown": (8, 8), "65-74": (6, 6), "<50": (6, 6)}


def test_question_4(cohort_db):
    r = count(defn([{"id": "c1", "kind": "any_of", "of": [
        {"kind": "biomarker", "name": "MSI", "call": ["high"]}, {"kind": "biomarker", "name": "TMB", "at_least": 10}]}],
        breakdown=["oncotree"]))
    assert r.patients == 15 and cells(r, "oncotree") == {"MEL": (8, 10), "COADREAD": (7, 20)}


def test_question_5(cohort_db):
    r = count(defn([alt("c1", ["ALK", "RET"], **{"class": ["fusion"]})]))
    assert r.patients == 8
    r = pivot(defn([alt("c1", ["ALK", "RET"], **{"class": ["fusion"]})], pivot={"rows": "c1.key", "cols": "oncotree"}))
    assert pcells(r) == {("ALK", "NSCLC"): None, ("RET", "NSCLC"): None}
    assert margins(r.row_totals) == {"ALK": None, "RET": None} and margins(r.col_totals) == {"NSCLC": 8}


def test_question_6(cohort_db):
    r = count(defn([{"id": "c1", "kind": "any_of", "of": [
        {"kind": "ihc", "marker": "ERBB2 (Her2/Neu)", "call": ["her2-low", "her2-ultralow"]},
        {"kind": "alteration", "gene": ["ERBB2"], "class": ["amplification", "mutation"]}]}], breakdown=["oncotree"]))
    assert r.patients == 17 and cells(r, "oncotree") == {"BRCA": (12, 15), "STAD": (5, 20)}
    assert any("IHC results are Caris only" in n for n in r.notes)


def test_question_7(cohort_db):
    c1 = {"id": "c1", "kind": "any_of", "of": [{"kind": "alteration", "gene": ["BRCA1"]},
                                               {"kind": "biomarker", "name": "LOH", "call": ["high"]}]}
    d = defn([c1], population=pop("OV", "PAAD"), breakdown=["oncotree"], pivot={"rows": "c1.key", "cols": "oncotree"})
    r = count(d)
    assert steps(r) == [25, 8] and cells(r, "oncotree") == {"OV": (8, 10)}
    r = pivot(d)
    assert pcells(r) == {("BRCA1", "OV"): 5, ("LOH", "OV"): 6}
    assert margins(r.row_totals) == {"BRCA1": 5, "LOH": 6} and margins(r.col_totals) == {"OV": 8}


def test_question_8(cohort_db):
    r = count(defn([{"id": "c1", "kind": "expression", "gene": ["TACSTD2"]},
                    {"id": "c2", "kind": "expression", "gene": ["TACSTD2"], "percentile_at_least": 75}],
                   population=pop("OV")))
    assert steps(r) == [10, 10, 5] and any("Expression percentiles" in n for n in r.notes)


def test_question_9(cohort_db):
    r = count(defn([ihc("c1", "CLDN18"), ihc("c2", "PD-L1", measure="CPS"),
                    ihc("c3", "CLDN18", call=["positive"]), ihc("c4", "PD-L1", measure="CPS", at_least=10)],
                   population=pop("STAD")))
    assert steps(r) == [20, 20, 20, 10, 5]


def test_question_12(cohort_db):
    d = defn([alt("c1", ["TP53", "CDKN2A", "IDH1"])], population=pop("CHOL"), pivot={"rows": "c1.key", "cols": "c1.sub"})
    r = count(d)
    assert r.patients == 9 and [(y.year, y.patients, y.complete) for y in r.by_year] == [(2025, 9, False)]
    r = pivot(d)
    assert pcells(r) == {("CDKN2A", "loss"): 7, ("TP53", "mutation"): None, ("IDH1", "mutation"): None}
    assert margins(r.row_totals) == {"CDKN2A": 7, "IDH1": None, "TP53": None}
    assert margins(r.col_totals) == {"loss": 7, "mutation": 8}


def test_question_13(cohort_db):
    r = count(defn([ihc("c1", "ER", call=["positive"]), alt("c2", ["PIK3CA"], aa=["H1047R", "E545K"])],
                   population=pop("BRCA")))
    assert steps(r) == [15, 10, 5]


def test_question_15(cohort_db):
    r = count(defn([{"id": "c1", "kind": "specimen", "site_type": ["metastatic"], "site": ["liver"]}],
                   breakdown=["oncotree"]))
    assert r.patients == 13
    assert cells(r, "oncotree") == {"COADREAD": (6, 20), "PAAD": (None, 15), "BRCA": (None, 15)}
    assert any("Specimen site and type" in n for n in r.notes)


def test_question_16(cohort_db):
    c1 = alt("c1", ["KRAS"], aa=["G12D"])
    r = count(defn([c1], population=pop("PAAD"), breakdown=["has_wts"]))
    assert steps(r) == [15, 10] and cells(r, "has_wts") == {"false": (5, 10), "true": (5, 5)}
    assert any("has_wts is Caris only" in n for n in r.notes)
    r = count(defn([c1, {"id": "c2", "kind": "specimen", "purity_at_least": 30}], population=pop("PAAD")))
    assert steps(r) == [15, 10, 5]


def test_question_20(cohort_db):
    r = count(defn([{"id": "c1", "kind": "actionability", "evidence": ["caris_level1", "fmi_fda_any_indication"]}],
                   breakdown=["oncotree"]))
    assert r.patients == 11 and cells(r, "oncotree") == {"MEL": (6, 10), "BRCA": (5, 15)}
    assert any("FDA flag" in n for n in r.notes)


# --- suppression -----------------------------------------------------------------------------------

def test_funnel_delta_rule(cohort_db):
    assert _funnel([20, 18, 10, 9, 3]) == [20, None, 10, None, None]
    r = count(defn([alt("c1", ["TP53", "CDKN2A"]), alt("c2", ["CDKN2A"]), alt("c3", ["TP53"])],
                   population=pop("CHOL"), breakdown=["oncotree"]))
    assert steps(r) == [15, 7, 7, None]
    # patients is None, so the whole-cohort rule applies.
    assert r.patients is None and r.reports is None and r.by_year == [] and r.breakdowns == {"oncotree": []}
    assert r.loosen == []   # every drop is within 4 of the hidden 6


def test_loosen(cohort_db):
    r = count(defn([alt("c1", ["IDH1"])], population=pop("CHOL")))
    assert steps(r) == [15, None] and [(s.drop, s.patients) for s in r.loosen] == [("c1", 15)]
    r = count(defn([ihc("c1", "CLDN18", call=["positive"]), ihc("c2", "PD-L1", measure="CPS", at_least=10),
                    ihc("c3", "ER", call=["positive"])], population=pop("STAD")))
    assert steps(r) == [20, 10, 5, 0] and r.patients == 0
    assert [(s.drop, s.patients) for s in r.loosen] == [("c3", 5)]


def test_loosen_does_not_repeat_hidden_funnel_steps(cohort_db):
    d = defn([alt("c1", ["TP53"]), alt("c2", ["KRAS"]), alt("c3", ["IDH1"])])
    for funnel in ([20, 17, 3], [20, 18, 3]):
        raw = suppress.RawCount(funnel=funnel, reports=0, by_year={}, year_complete={}, breakdowns={}, denominators={},
                                loosen={"c1": 20, "c2": funnel[1], "c3": 9})
        r = suppress.suppress_count(d, raw)
        assert steps(r) == [20, None, None] and r.patients is None
        # c2 would repeat the hidden step; c1 repeats shown step 0, which reveals nothing new.
        assert [(s.drop, s.patients) for s in r.loosen] == [("c1", 20), ("c3", 9)]
    raw.loosen["c3"] = 16   # 1..4 away from shown step 0 (20)
    assert [s.drop for s in suppress.suppress_count(d, raw).loosen] == ["c1"]


def test_line_rule():
    assert _line([12, None], 14) == [None, None]
    assert _line([None, None, 5], 20) == [None, None, 5]
    assert _line([0, None], 5) == [0, None]        # a zero is never chosen
    assert _line([7, 7, None], 20) == [None, 7, None]   # ties go to the first
    assert _line([12, 8], None) == [12, None]      # the total is the one hidden value


def test_floor():
    assert [floor(n) for n in (None, 0, 1, 4, 5, 6)] == [None, 0, None, None, 5, 6]


def line_nones(r):
    """Every line of a pivot result, absent cells as 0, as lists of values (total last)."""
    rows, cols = sorted(margins(r.row_totals)), sorted(margins(r.col_totals))
    cell, rt, ct = pcells(r), margins(r.row_totals), margins(r.col_totals)
    lines = [[cell.get((a, b), 0) for b in cols] + [rt[a]] for a in rows]
    lines += [[cell.get((a, b), 0) for a in rows] + [ct[b]] for b in cols]
    lines += [list(rt.values()) + [r.patients], list(ct.values()) + [r.patients]]
    return lines


@pytest.mark.parametrize("d", [
    defn(pivot={"rows": "oncotree", "cols": "year"}),
    defn([alt("c1", ["ALK", "RET"], **{"class": ["fusion"]})], pivot={"rows": "c1.key", "cols": "oncotree"}),
    defn([alt("c1", ["TP53", "CDKN2A", "IDH1"])], population=pop("CHOL"), pivot={"rows": "c1.key", "cols": "c1.sub"}),
    defn(pivot={"rows": "vendor", "cols": "assay_class"}),
    defn([alt("c1", ["KRAS"])], pivot={"rows": "oncotree", "cols": "site_type"}),
])
def test_pivot_two_way(cohort_db, d):
    r = pivot(d)
    assert r.patients is not None
    for line in line_nones(r):
        assert sum(v is None for v in line) != 1, line


def test_pivot_whole_cohort_rule(cohort_db):
    r = pivot(defn([alt("c1", ["TP53", "CDKN2A"]), alt("c2", ["CDKN2A"]), alt("c3", ["TP53"])],
                   population=pop("CHOL"), pivot={"rows": "c1.key", "cols": "vendor"}))
    assert r.patients is None and r.cells == [] and r.row_totals == [] and r.col_totals == []


def test_pivot_rare_fact_values_become_other(cohort_db):
    r = pivot(defn([ihc("c1", "ERBB2 (Her2/Neu)")], pivot={"rows": "c1.val", "cols": "vendor"}))
    assert margins(r.row_totals) == {"her2-low": None, "her2-ultralow": 5, "other": None}   # 'positive' has 2 patients, so is "other"
    r = pivot(defn([alt("c1", ["RET"])], pivot={"rows": "c1.val", "cols": "c1.sub"}))
    assert margins(r.row_totals) == {"other": 5} and margins(r.col_totals) == {"other": 5}
    text = json.dumps(r.model_dump())
    assert "KIF5B" not in text and "M918T" not in text   # a fusion partner and a protein change, 2 and 3 patients
    r = pivot(defn([alt("c1", ["KRAS", "ALK"])], pivot={"rows": "c1.key", "cols": "c1.val"}))
    assert {"KRAS", "ALK"} >= set(margins(r.row_totals))   # `key` is a vocabulary value the caller chose


def test_pivot_margins_count_only_patients_in_a_cell(tmp_path, monkeypatch):
    m = Mart()
    for i in range(6):   # c1 matches the 2022 report, c2 the 2024 one: nothing in a 2024 row of a c1 column
        m.report(f"p{i}", f"p{i}a", "BRCA", "Breast", "caris", 2022)
        m.report(f"p{i}", f"p{i}b", "BRCA", "Breast", "caris", 2024)
        m.mutation(f"p{i}a", "KRAS", "G12C")
        m.fact(f"p{i}b", "ihc", "ER", "sp1", "positive")
    path = str(tmp_path / "two.duckdb")
    write_mart(path, m)
    use_mart(path, m, monkeypatch)
    r = pivot(defn([alt("c1", ["KRAS"]), ihc("c2", "ER")], pivot={"rows": "year", "cols": "c1.key"}))
    assert pcells(r) == {("2022", "KRAS"): 6} and margins(r.row_totals) == {"2022": 6}
    for line in line_nones(r):
        assert sum(v is None for v in line) != 1, line


def test_unlisted_small_remainder_is_a_hidden_value(tmp_path, monkeypatch):
    m = Mart()
    for i in range(12):
        m.report(f"f{i}", f"f{i}r", "BRCA", "Breast", "caris", 2022 if i < 10 else None)
        m.fact(f"f{i}r", "ihc", "ER", "sp1", "positive")
    for i in range(6):   # female, untested
        m.report(f"u{i}", f"u{i}r", "BRCA", "Breast", "caris", 2022)
    for i in range(3):   # the whole male remainder: in the population, not in the cohort
        m.report(f"m{i}", f"m{i}r", "BRCA", "Breast", "caris", 2022, sex="male")
    path = str(tmp_path / "remainder.duckdb")
    write_mart(path, m)
    use_mart(path, m, monkeypatch)
    r = count(defn([ihc("c1", "ER")], breakdown=["sex"]))
    assert r.patients == 12 and r.denominator == 21
    assert cells(r, "sex") == {"female": (12, None)}   # a shown 18 beside 21 would give the male 3
    # The 2 patients with no dated report are the whole undated remainder of by_year.
    assert [(y.year, y.patients) for y in r.by_year] == [(2022, None)]


def test_compile_validates_names_it_puts_in_the_sql():
    d = defn([alt("c1", ["KRAS"])], pivot={"rows": "oncotree", "cols": "year"})
    bad = Pivot.model_construct(rows="(SELECT 1); --", cols="year")
    with pytest.raises(DefinitionError, match="not a pivot axis"):
        compile_pivot(d.model_copy(update={"pivot": bad}))
    with pytest.raises(DefinitionError, match="names no criterion"):
        compile_pivot(d.model_copy(update={"pivot": Pivot.model_construct(rows="c9.key", cols="year")}))
    with pytest.raises(DefinitionError, match="not a breakdown dimension"):
        compile(d.model_copy(update={"breakdown": ["sex; DROP TABLE x"]}))


def walk(x):
    """Every (key, value) pair anywhere in a result; list items come with key None."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield None, v
            yield from walk(v)


CHOL = pop("CHOL")
LEAK_DEFS = [
    defn([alt("c1", ["KRAS"], aa=["G12C"])], population=pop("NSCLC", years=[2023, 2025]), breakdown=["oncotree", "sex"]),
    defn(pivot={"rows": "oncotree", "cols": "year"}),
    defn(population=pop("COADREAD"), breakdown=["age_band", "site_type"]),
    defn([alt("c1", ["ALK", "RET"], **{"class": ["fusion"]})], pivot={"rows": "c1.key", "cols": "oncotree"}),
    defn([alt("c1", ["TP53", "CDKN2A", "IDH1"])], population=CHOL, breakdown=["vendor"],
         pivot={"rows": "c1.key", "cols": "c1.sub"}),
    defn([alt("c1", ["TP53", "CDKN2A"]), alt("c2", ["CDKN2A"]), alt("c3", ["TP53"])], population=CHOL,
         breakdown=["oncotree"]),
    defn([alt("c1", ["IDH1"])], population=CHOL),
    defn([ihc("c1", "CLDN18", call=["positive"]), ihc("c2", "PD-L1", measure="CPS", at_least=10),
          ihc("c3", "ER", call=["positive"])], population=pop("STAD")),
    defn([{"id": "c1", "kind": "specimen", "site_type": ["metastatic"], "site": ["liver"]}], breakdown=["oncotree"]),
    defn([ihc("c1", "ERBB2 (Her2/Neu)")], pivot={"rows": "c1.val", "cols": "vendor"}),
    defn([alt("c1", ["RET"])], pivot={"rows": "c1.val", "cols": "c1.sub"}),
]


@pytest.mark.parametrize("d", LEAK_DEFS)
def test_no_small_numbers_and_no_ids(cohort_db, d):
    results = [count(d)] + ([pivot(d)] if d.pivot else [])
    for result in results:
        for k, v in walk(result.model_dump()):
            assert k not in ("research_id", "report_id")
            assert not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4), (k, v)
            assert not (isinstance(v, str) and v in cohort_db["ids"]), (k, v)


def test_vocabulary_has_no_small_numbers_and_no_ids(cohort_db):
    for k, v in walk(vocabulary().model_dump()):
        assert not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4), (k, v)
        assert not (isinstance(v, str) and v in cohort_db["ids"]), (k, v)
    assert all(e.patients >= MIN_CELL for e in vocabulary().entries)        # kept to rank search
    assert all("patients" not in e for e in vocabulary().model_dump()["entries"])


# --- definition ---------------------------------------------------------------------------------------

BASE = {"criteria": [{"id": "c1", "kind": "alteration", "gene": ["KRAS"], "aa": ["G12C"]}]}


def test_cohort_id_stable():
    base = parse(BASE)
    assert cohort_id(base) == "v1-2602b9a5ad67dd6b"      # pinned: a change orphans saved cohorts
    same = [
        {"criteria": [{"id": "c1", "kind": "alteration", "gene": ["kras", "KRAS"], "aa": ["G12C", "G12C"],
                       "tier": ["pathogenic", "likely_pathogenic"], "mode": "include", "class": ["mutation"]}]},
        {**BASE, "name": "other", "breakdown": ["oncotree"], "pivot": {"rows": "oncotree", "cols": "year"}},
        {"criteria": [{"id": "c7", "kind": "alteration", "gene": ["KRAS"], "aa": ["G12C"]}]},
        {"criteria": [{"id": "c1", "kind": "alteration", "gene": [" KRAS "], "aa": ["G12C"], "tier": []}]},
    ]
    for data in same:
        assert cohort_id(parse(data)) == cohort_id(base)
    assert parse(same[0]) == base
    assert cohort_id(parse({"criteria": [{"id": "c1", "kind": "alteration", "gene": ["KRAS"], "aa": ["G12D"]}]})) \
        != cohort_id(base)
    assert cohort_id(parse({**BASE, "population": {"oncotree": ["NSCLC"]}})) != cohort_id(base)
    a = {"id": "c1", "kind": "alteration", "gene": ["KRAS"]}
    b = {"id": "c2", "kind": "biomarker", "name": "MSI", "call": ["high"]}
    assert cohort_id(parse({"criteria": [a, b]})) == cohort_id(parse({"criteria": [{**b, "id": "c1"}, {**a, "id": "c2"}]}))
    m1, m2 = {"kind": "biomarker", "name": "MSI", "call": ["high"]}, {"kind": "alteration", "gene": ["KRAS"]}
    assert parse({"criteria": [{"id": "c1", "kind": "any_of", "of": [m1, m2]}]}) \
        == parse({"criteria": [{"id": "c1", "kind": "any_of", "of": [m2, m1]}]})


@pytest.mark.parametrize("data, fragment", [
    ({"criteria": [{"id": "c1", "kind": "sequence"}]}, "criterion kind 'sequence' is not supported yet"),
    ({"criteria": [{"id": "c1", "kind": "data"}]}, "criterion kind 'data' is not supported yet"),
    ({"criteria": [{"id": "c1", "kind": "tested_negative", "gene": ["TP53"]}]}, "'tested_negative' is not supported yet"),
    ({"criteria": [{"id": "c1", "kind": "exclude"}]}, "criterion kind 'exclude' is not supported yet"),
    ({"criteria": [{"id": "c1", "kind": "any_of", "of": [{"kind": "exclude"}, {"kind": "ihc", "marker": "ER"}]}]},
     "criterion kind 'exclude' is not supported yet"),
    ({"criteria": [{**BASE["criteria"][0], "mode": "exclude"}]}, "criterion mode 'exclude' is not supported yet"),
    ({"criteria": [{**BASE["criteria"][0], "mode": "tested_negative"}]}, "criteria are include-only"),
    ({**BASE, "scope": "report"}, "scope 'report' is not supported yet"),
    ({**BASE, "version": 2}, "unsupported definition version 2"),
])
def test_deferred_features_rejected(data, fragment):
    with pytest.raises(DefinitionError, match=fragment):
        parse(data)


@pytest.mark.parametrize("criterion, fragment", [
    (alt("c1", ["KRAS", "NRAS"], aa=["G12C"]), "aa needs exactly one gene"),
    (alt("c1", ["KRAS"], aa=["G12C"], **{"class": ["fusion"]}), "aa applies to class mutation only"),
    ({"id": "c1", "kind": "biomarker", "name": "TMB", "at_least": 11}, "at_least must be one of"),
    ({"id": "c1", "kind": "ihc", "marker": "PD-L1", "measure": "CPS", "at_least": 5}, "at_least must be one of"),
    ({"id": "c1", "kind": "biomarker", "name": "MSI", "at_least": 10}, "TMB only"),
    ({"id": "c1", "kind": "biomarker", "name": "TMB", "call": ["high"], "at_least": 10}, "mutually exclusive"),
    ({"id": "c1", "kind": "ihc", "marker": "PD-L1", "at_least": 10}, "at_least needs measure"),
    ({"id": "c1", "kind": "ihc", "marker": "PD-L1", "call": ["positive"], "measure": "CPS"}, "call excludes measure"),
    ({"id": "c1", "kind": "specimen"}, "specimen needs"),
    ({"id": "c1", "kind": "expression", "gene": ["TACSTD2"], "percentile_at_least": 60}, "must be one of"),
    (alt("c1", [" "]), "empty string"),
])
def test_static_validation(criterion, fragment):
    with pytest.raises(DefinitionError, match=fragment):
        parse({"criteria": [criterion]})


def test_static_validation_definition_level():
    a, b = alt("c1", ["KRAS"]), alt("c2", ["TP53"])
    for data, fragment in [
        ({"criteria": [a, {**b, "id": "c1"}]}, "duplicate criterion id"),
        ({"criteria": [{**a, "id": None}]}, "needs an id"),
        ({"criteria": [a], "pivot": {"rows": "oncotree", "cols": "oncotree"}}, "must differ"),
        ({"criteria": [a], "pivot": {"rows": "oncotree", "cols": "c9.key"}}, "unknown criterion 'c9'"),
        ({"criteria": [a], "pivot": {"rows": "oncotree", "cols": "nonsense"}}, "not a dimension"),
        ({"criteria": [{"id": "c1", "kind": "specimen", "site": ["liver"]}], "pivot": {"rows": "c1.val", "cols": "year"}},
         "specimen criterion cannot be a pivot axis"),
        ({"criteria": [{"id": "c1", "kind": "any_of", "of": [{"kind": "specimen", "site": ["liver"]}, {"kind": "ihc", "marker": "ER"}]}],
          "pivot": {"rows": "c1.val", "cols": "year"}}, "specimen criterion cannot be a pivot axis"),
        ({"criteria": [{"id": "c1", "kind": "any_of", "of": [{**a, "id": "c2"}, b]}]}, "take no id"),
        ({"breakdown": ["oncotree", "oncotree"]}, "duplicate"),
        ({"population": {"years": [2025, 2022]}}, "from <= to"),
        ({"criteria": [{**a, "extra": 1}]}, "Extra inputs"),
    ]:
        with pytest.raises(DefinitionError, match=fragment):
            parse(data)


def test_operations():
    d = parse({"criteria": [alt("c1", ["KRAS"]), {"id": "c3", "kind": "ihc", "marker": "ER"}],
               "pivot": {"rows": "c1.key", "cols": "year"}})
    before = d.model_copy(deep=True)
    added = apply(d, {"op": "add_criterion", "criterion": {"kind": "biomarker", "name": "MSI"}})
    assert [c.id for c in added.criteria] == ["c1", "c3", "c4"]
    assert apply(d, {"op": "add_criterion", "criterion": {"id": "c9", "kind": "biomarker", "name": "MSI"}}).criteria[-1].id == "c9"
    assert apply(Definition(), {"op": "add_criterion", "criterion": {"kind": "biomarker", "name": "MSI"}}).criteria[0].id == "c1"
    removed = apply(d, {"op": "remove_criterion", "id": "c1"})
    assert [c.id for c in removed.criteria] == ["c3"] and removed.pivot is None      # the pivot referenced c1
    assert apply(d, {"op": "remove_criterion", "id": "c3"}).pivot == d.pivot
    updated = apply(d, {"op": "update_criterion", "id": "c3", "criterion": {"id": "c8", "kind": "ihc", "marker": "PR"}})
    assert [(c.id, c.kind) for c in updated.criteria] == [("c1", "alteration"), ("c3", "ihc")]
    assert updated.criteria[1].marker == "PR"
    assert apply(d, {"op": "set_population", "population": {"oncotree": ["BRCA"]}}).population.oncotree == ["BRCA"]
    assert apply(d, {"op": "set_breakdown", "breakdown": ["sex"]}).breakdown == ["sex"]
    assert apply(d, {"op": "set_pivot", "pivot": None}).pivot is None
    assert apply(d, {"op": "set_pivot", "pivot": {"rows": "sex", "cols": "year"}}).pivot.rows == "sex"
    assert apply(d, {"op": "rename", "name": "renamed"}).name == "renamed"
    assert d == before                                                              # the input is never changed
    for op, fragment in [
        ({"op": "remove_criterion", "id": "c9"}, "unknown criterion id 'c9'"),
        ({"op": "update_criterion", "id": "c9", "criterion": {"kind": "ihc", "marker": "ER"}}, "unknown criterion id"),
        ({"op": "add_criterion", "criterion": {"id": "c1", "kind": "ihc", "marker": "ER"}}, "already exists"),
        ({"op": "add_criterion", "criterion": {"kind": "exclude"}}, "not supported yet"),
        ({"op": "set_pivot", "pivot": {"rows": "sex", "cols": "sex"}}, "must differ"),
        ({"op": "set_breakdown", "breakdown": ["nonsense"]}, "breakdown"),
        ({"op": "nonsense"}, "nonsense"),
    ]:
        with pytest.raises(DefinitionError, match=fragment):
            apply(d, op)
    assert d == before


def test_operation_checks_vocabulary(cohort_db):
    with pytest.raises(DefinitionError, match="G13D"):
        apply(Definition(), {"op": "add_criterion", "criterion": alt("c1", ["KRAS"], aa=["G13D"])}, vocabulary())


def test_json_schema():
    schema = json_schema()
    kinds = {d["properties"]["kind"]["const"] for d in schema["$defs"].values() if "kind" in d.get("properties", {})}
    assert kinds == {"alteration", "biomarker", "ihc", "expression", "specimen", "actionability", "any_of"}
    assert "class" in schema["$defs"]["Alteration"]["properties"] and "class_" not in schema["$defs"]["Alteration"]["properties"]
    ops = {o["properties"]["op"]["const"] for o in operation_json_schema()["$defs"].values() if "op" in o.get("properties", {})}
    assert ops == {"add_criterion", "remove_criterion", "update_criterion", "set_population", "set_breakdown",
                   "set_pivot", "rename"}
    # The COHORT_DISCOVERY.md §3.1 example, minus the phase 2 exclude criterion.
    d = parse({"version": 1, "name": "HER2-low breast", "population": {"oncotree": ["BRCA"], "age_band": ["<50"], "years": [2020, 2025]},
               "criteria": [{"id": "c1", "kind": "ihc", "marker": "ERBB2 (Her2/Neu)", "measure": "TPS", "at_least": 1}],
               "scope": "patient", "breakdown": ["oncotree", "has_wts"], "pivot": {"rows": "oncotree", "cols": "year"}})
    assert d.criteria[0].at_least == 1.0 and CUT_POINTS["ihc.TPS"][0] == 1.0


def test_data_notes():
    notes = data_notes(parse({}))
    assert len(notes) == 1 and notes[0].startswith("Stage, treatment")
    d = parse({"population": {"age_band": ["<50"]}, "breakdown": ["site_type", "has_wts"],
               "criteria": [{"id": "c1", "kind": "any_of", "of": [{"kind": "ihc", "marker": "ER"},
                                                                   {"kind": "expression", "gene": ["MYC"]}]},
                            {"id": "c2", "kind": "actionability", "evidence": ["fmi_fda_any_indication"]}]})
    assert len(data_notes(d)) == 7 and data_notes(d)[-1].startswith("Stage")


# --- vocabulary ---------------------------------------------------------------------------------------

def test_vocabulary_floor_and_check(cohort_db):
    v = vocabulary()
    assert all(e.patients >= MIN_CELL for e in v.entries)
    assert v.years == (2022, 2025)
    assert "THYM" not in v.allowed("population.oncotree") and "NSCLC" in v.allowed("population.oncotree")
    assert "positive" not in v.allowed("ihc.call", "ERBB2 (Her2/Neu)") and "positive" in v.allowed("ihc.call", "ER")
    assert "G13D" not in v.allowed("alteration.aa", "KRAS") and "G12C" in v.allowed("alteration.aa", "KRAS")
    for bad, fragment in [
        (defn(population=pop("THYM")), r"population.oncotree: 'THYM' is not in the vocabulary"),
        (defn([ihc("c1", "ERBB2 (Her2/Neu)", call=["positive"])]), r"criteria.c1.call: 'positive' is not in the vocabulary for ERBB2"),
        (defn([alt("c1", ["KRAS"], aa=["G13D"])]), r"criteria.c1.aa: 'G13D' is not in the vocabulary for KRAS"),
        (defn([alt("c1", ["NOPE"])]), r"criteria.c1.gene: 'NOPE'"),
        (defn(population={"years": [2019, 2025]}), "population.years"),
        (defn([{"id": "c1", "kind": "any_of", "of": [{"kind": "alteration", "gene": ["NOPE"]}, {"kind": "ihc", "marker": "ER"}]}]),
         r"criteria.c1.of.\d.gene"),
    ]:
        with pytest.raises(DefinitionError, match=fragment):
            v.check(bad)
        with pytest.raises(DefinitionError):
            count(bad)
    for d in LEAK_DEFS:
        v.check(d)


def test_search(cohort_db):
    hits = [(e.field, e.value) for e in vocabulary().search("erbb2")]
    assert ("alteration.gene", "ERBB2") in hits and ("ihc.marker", "ERBB2 (Her2/Neu)") in hits
    assert hits[0] == ("alteration.gene", "ERBB2")      # exact before prefix
    v = vocabulary()
    assert v.search("") == [] and v.search("x" * 101) == [] and len(v.search("a", limit=1000)) <= 50
    assert len(v.search("a", limit=0)) == 1


def test_search_field_and_parent(cohort_db):
    v = vocabulary()
    sexes = v.search("", field="population.sex")
    assert sexes and {e.field for e in sexes} == {"population.sex"}
    assert {e.value for e in sexes} == {e.value for e in v.entries if e.field == "population.sex"}
    aa = v.search("", field="alteration.aa", parent="KRAS")
    assert "G12C" in [e.value for e in aa] and {(e.field, e.parent) for e in aa} == {("alteration.aa", "KRAS")}
    assert [e.patients for e in aa] == sorted((e.patients for e in aa), reverse=True)
    assert [e.value for e in v.search("g12", field="alteration.aa", parent="KRAS")] == [e.value for e in aa if "G12" in e.value]
    assert v.search("", field="no.such") == [] and v.search("") == [] and v.search("", parent="KRAS") == []


# --- compile ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("criterion, fragments, values", [
    (alt("c1", ["KRAS"], aa=["G12C"]), ["f.kind = 'alteration' AND list_contains($k0_gene, upper(f.key))",
                                        "f.sub = 'mutation' AND list_contains($k0_aa, f.val)",
                                        "(f.sub <> 'mutation' OR list_contains($k0_tier, f.tier))"], ["KRAS", "G12C"]),
    ({"id": "c1", "kind": "biomarker", "name": "TMB", "at_least": 10},
     ["f.kind = 'biomarker' AND f.key = $k0_name", "f.num >= $k0_at_least"], ["TMB", 10.0]),
    (ihc("c1", "CLDN18", clone="43-14A", call=["positive"]),
     ["f.kind = 'ihc' AND f.key = $k0_marker", "f.sub = $k0_clone", "list_contains($k0_call, f.val)"],
     ["CLDN18", "43-14a", ["positive"]]),
    (ihc("c1", "PD-L1", measure="CPS", at_least=10), ["f.unit = $k0_measure", "f.num >= $k0_at_least"], ["CPS", 10.0]),
    ({"id": "c1", "kind": "expression", "gene": ["TACSTD2"], "percentile_at_least": 75},
     ["f.kind = 'expression' AND list_contains($k0_gene, upper(f.key))", "f.num >= $k0_pct"], ["TACSTD2", 75.0]),
    ({"id": "c1", "kind": "actionability", "evidence": ["caris_level1"]},
     ["f.kind = 'actionability' AND list_contains($k0_evidence, f.key)"], [["caris_level1"]]),
    ({"id": "c1", "kind": "specimen", "site_type": ["metastatic"], "site": ["liver"], "purity_at_least": 30},
     ["f.key = 'site_type' AND list_contains($k0_site_type, f.val)", "f.key = 'site' AND list_contains($k0_site, f.val)",
      "f.key = 'purity' AND f.num >= $k0_purity"], [["metastatic"], ["liver"], 30.0]),
    ({"id": "c1", "kind": "any_of", "of": [{"kind": "alteration", "gene": ["ERBB2"]}, ihc("", "ER") | {"id": None}]},
     ["list_contains($k0m0_gene", "f.key = $k0m1_marker", ") OR ("], ["ERBB2", "ER"]),
])
def test_compile_each_kind(criterion, fragments, values):
    d = defn([criterion], population=pop("NSCLC", years=[2022, 2024]))
    sql, params = compile(d)
    assert all(f in sql for f in fragments), sql
    flat = [v for p in params.values() for v in (p if isinstance(p, list) else [p])]
    assert all((v in flat) or (v in params.values()) for v in values)
    for value in ("KRAS", "G12C", "CLDN18", "NSCLC", "TACSTD2", "metastatic", "liver", "ERBB2"):
        assert value not in sql
    assert not any(s in sql for s in ("unified.", "caris.", "fmi."))
    assert "mart.fact" in sql and "mart.report" in sql
    assert params["pop_oncotree"] == ["NSCLC"] and (params["pop_year_from"], params["pop_year_to"]) == (2022, 2024)
    assert compile(d) == (sql, params)


def test_compile_pivot_requires_pivot_and_binds_values():
    with pytest.raises(DefinitionError):
        compile_pivot(defn())
    sql, params = compile_pivot(defn([alt("c1", ["KRAS"])], pivot={"rows": "c1.key", "cols": "oncotree"}))
    assert "KRAS" not in sql and params["k0_gene"] == ["KRAS"]


def test_compile_omits_empty_clauses():
    sql, params = compile(defn())
    assert "pop_" not in sql and params == {}


# --- real file ---------------------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(DEID_DB), reason="no real de-id file")
def test_real_db_matches_hand_written_sql():
    if deid_lacks_mart():
        pytest.skip("real de-id file predates mart.fact (#33)")
    result = count(parse({"criteria": [{"id": "c1", "kind": "alteration", "gene": ["TP53"], "aa": ["R175H"]}]}))
    con = server.get_db()
    try:
        (n,) = con.execute("""SELECT count(DISTINCT research_id) FROM unified.variant
                              WHERE gene = 'TP53' AND regexp_replace(hgvs_p, '^p\\.', '') = 'R175H'
                                AND tier IN ('pathogenic', 'likely_pathogenic')""").fetchone()
    finally:
        con.close()
    assert result.patients == floor(n)
