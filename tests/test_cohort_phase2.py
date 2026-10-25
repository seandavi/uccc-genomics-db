"""Cohort phase 2 (#38): exclusion, tested negative, report scope, data and sequence criteria, the
neighbour check. docs/specs/38-cohort-phase-2-exclusion-report-scope.md.

A synthetic mart of its own (`build_phase2_mart`); every value is invented. Patients are
`<prefix><i>`; all reports are Caris tissue, collected `YYYY-06-01`, female and pathogenic unless noted.
  NSCLC l0-l31     KRAS G12D l0-l26; STK11 l0-l5, l20-l24; KEAP1 l6-l8, l27-l28; l20-l24 have two reports
  PAAD  q0-q9      KRAS G12D q0-q1
  COADREAD d0-d29  KRAS d0-d7, NRAS d8-d12, BRAF d13-d17; tested negative KRAS d8-d24, NRAS d18-d22
  GIST  g0-g29     KRAS g0-g9; tested negative KRAS g10-g26 (g27-g29 have no KRAS result)
  BRCA  s0-s9      tissue and liquid reports (dates in the build), ESR1
  MEL   x0-x16 y0-y5   TMB by vendor (x have both vendors)
  PRAD  h0-h14     liquid; DNMT3A h0-h4, TET2 h5-h9
  IDC e0-e29, ILC w0-w29, HGSOC z0-z29   ER positive, PIK3CA, TP53 and BRCA1
"""
from datetime import date

import pytest

from test_cohort import (Mart, alt, cells, defn, ihc, line_nones, margins, pcells, pop, steps, use_mart, walk,
                         write_mart)
from uccc_genomics_mcp.cohort import (DefinitionError, apply, count, data_notes, parse, pivot,
                                      vocabulary)
from uccc_genomics_mcp.cohort import queries, suppress
from uccc_genomics_mcp.cohort.compile import compile, compile_pivot
from uccc_genomics_mcp.cohort.definition import MAX_NEIGHBOURS, neighbours
from uccc_genomics_mcp.cohort.suppress import RawCount, RawNeighbour, RawPivot, RawPivotNeighbour, _funnel


def ids(prefix, lo, hi):
    return [f"{prefix}{i}" for i in range(lo, hi)]


def build_phase2_mart() -> Mart:
    m = Mart()
    male = {f"l{i}" for i in (0, 1, 2, 9, 10, 11, 12, 13)}
    for i in range(32):   # NSCLC
        pid = f"l{i}"
        sex = "male" if pid in male else "female"
        if 20 <= i < 25:
            m.report(pid, f"{pid}a", "NSCLC", "Lung", "caris", 2023, sex=sex)
            m.report(pid, f"{pid}b", "NSCLC", "Lung", "caris", 2024, sex=sex)
        else:
            m.report(pid, f"{pid}r", "NSCLC", "Lung", "caris", 2025 if i in (25, 26) else 2024, sex=sex)
    for i in range(27):
        m.mutation(f"l{i}a" if 20 <= i < 25 else f"l{i}r", "KRAS", "G12D")
    for i in [*range(6), *range(20, 25)]:
        m.mutation(f"l{i}b" if i >= 20 else f"l{i}r", "STK11", "Q37*")
    for i in (6, 7, 8, 27, 28):
        m.mutation(f"l{i}r", "KEAP1", "G333C")

    for i in range(10):   # PAAD
        m.report(f"q{i}", f"q{i}r", "PAAD", "Pancreas", "caris", 2024)
        if i < 2:
            m.mutation(f"q{i}r", "KRAS", "G12D")

    for i in range(30):   # COADREAD
        m.report(f"d{i}", f"d{i}r", "COADREAD", "Bowel", "caris", 2023)
        for lo, hi, gene, aa in ((0, 8, "KRAS", "G12D"), (8, 13, "NRAS", "Q61K"), (13, 18, "BRAF", "V600E")):
            if lo <= i < hi:
                m.mutation(f"d{i}r", gene, aa)
        if 8 <= i < 25:
            m.fact(f"d{i}r", "tested_negative", "KRAS", sub="wildtype")
        if 18 <= i < 23:
            m.fact(f"d{i}r", "tested_negative", "NRAS", sub="wildtype")

    for i in range(30):   # GIST
        m.report(f"g{i}", f"g{i}r", "GIST", "Stomach", "caris", 2024)
        if i < 10:
            m.mutation(f"g{i}r", "KRAS", "G12D")
        elif i < 27:
            m.fact(f"g{i}r", "tested_negative", "KRAS", sub="wildtype")

    for i in range(10):   # BRCA
        m.report(f"s{i}", f"s{i}t", "BRCA", "Breast", "caris", 2022, collected_on=date(2022, 3, 1))
        if i < 9:
            when = date(2023, 5, 1) if i < 7 else date(2022, 3, 1) if i == 7 else date(2021, 5, 1)
            m.report(f"s{i}", f"s{i}l", "BRCA", "Breast", "caris", when.year, assay_class="liquid", collected_on=when)
        m.mutation(f"s{i}l" if i < 5 else f"s{i}t", "ESR1", "Y537S")

    for i in range(23):   # MEL: x0-x16 have both vendors, y0-y5 Caris only
        m.report(f"{'x' if i < 17 else 'y'}{i if i < 17 else i - 17}", f"{'x' if i < 17 else 'y'}{i if i < 17 else i - 17}c",
                 "MEL", "Skin", "caris", 2024, collected_on=date(2024, 2, 1))
        pid = f"x{i}" if i < 17 else f"y{i - 17}"
        m.fact(f"{pid}c", "biomarker", "TMB", val="low" if i < 7 or i >= 17 else "high")
        if i < 17:
            m.report(pid, f"{pid}f", "MEL", "Skin", "fmi", 2024, collected_on=date(2024, 8, 1))
            m.fact(f"{pid}f", "biomarker", "TMB", val="high" if 7 <= i < 12 else "low")

    for i in range(15):   # PRAD
        m.report(f"h{i}", f"h{i}r", "PRAD", "Prostate", "caris", 2024, assay_class="liquid")
        if i < 5:
            m.mutation(f"h{i}r", "DNMT3A", "R882H")
        elif i < 10:
            m.mutation(f"h{i}r", "TET2", "Q810*")

    for prefix, onco, organ, er, pik in (("e", "IDC", "Breast", 12, (0, 1, 2, 12, 13)),
                                         ("w", "ILC", "Breast", 12, (0, 1, 2, 3, 4, 12, 13))):
        for i in range(30):
            m.report(f"{prefix}{i}", f"{prefix}{i}r", onco, organ, "caris", 2024)
            if i < er:
                m.fact(f"{prefix}{i}r", "ihc", "ER", "sp1", "positive")
            if i in pik:
                m.mutation(f"{prefix}{i}r", "PIK3CA", "E545K")
    for i in range(30):   # HGSOC
        m.report(f"z{i}", f"z{i}r", "HGSOC", "Ovary", "caris", 2024)
        if i < 10:
            m.fact(f"z{i}r", "ihc", "ER", "sp1", "positive")
        if i < 2 or 20 <= i < 25:
            m.mutation(f"z{i}r", "TP53", "R273H")
            m.mutation(f"z{i}r", "BRCA1", "E1836K")
    return m


@pytest.fixture(scope="module")
def phase2_file(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("phase2") / "cohort.duckdb")
    m = build_phase2_mart()
    write_mart(path, m)
    return path, m


@pytest.fixture
def db(phase2_file, monkeypatch):
    path, m = phase2_file
    return use_mart(path, m, monkeypatch)


def exclude(c):
    return {**c, "mode": "exclude"}


def raw_count(d):
    con = queries.get_db()
    try:
        return queries._run_count(con, d)
    finally:
        con.close()


def raw_funnel(d):
    return raw_count(d).funnel


def shown(d):
    return steps(count(d))


KRAS = alt("c1", ["KRAS"])
NSCLC = pop("NSCLC")


# --- the questions ---------------------------------------------------------------------------------

def test_question_10(db):
    c2 = alt("c2", ["STK11", "KEAP1"])
    assert shown(defn([alt("c1", ["KRAS"]), c2], population=NSCLC)) == [32, 27, 14]
    assert shown(defn([alt("c1", ["KRAS"]), exclude(c2)], population=NSCLC)) == [32, 27, 13]
    assert shown(defn([alt("c1", ["KRAS"]), c2], population=NSCLC, scope="report")) == [32, 27, 9]
    assert shown(defn([alt("c1", ["KRAS"]), exclude(c2)], population=NSCLC, scope="report")) == [32, 27, 18]


def test_question_11(db):
    c1, c2 = exclude(alt("c1", ["KRAS", "NRAS"])), exclude(alt("c2", ["BRAF"], aa=["V600E"]))
    r = count(defn([c1, c2], population=pop("COADREAD")))
    assert steps(r) == [30, 17, 12] and any("An exclusion drops patients" in n for n in r.notes)
    c3 = alt("c3", ["KRAS"], mode="tested_negative")
    r = count(defn([c1, c2, c3], population=pop("COADREAD")))
    assert steps(r) == [30, 17, 12, 7]
    assert any(n.startswith("Tested negative also needs") for n in r.notes)
    # Every listed gene must be tested negative: "any gene" would give 12, KRAS alone 17.
    r = count(defn([alt("c1", ["KRAS", "NRAS"], mode="tested_negative")], population=pop("COADREAD")))
    assert steps(r) == [30, 5]


def test_question_14(db):
    seq = {"id": "c1", "kind": "sequence", "first": [{"kind": "data", "has": "tissue"}],
           "then": [{"kind": "data", "has": "liquid"}]}
    r = count(defn([seq]))
    assert r.patients == 7 and [(y.year, y.patients) for y in r.by_year] == [(2023, 7)]   # not the same-day s7 or earlier s8
    assert any(n.startswith("Report order uses") for n in r.notes)
    r = count(defn([{**seq, "then": [{"kind": "alteration", "gene": ["ESR1"]}, {"kind": "data", "has": "liquid"}]}]))
    assert r.patients == 5
    both = [alt("c1", ["ESR1"]), {"id": "c2", "kind": "data", "has": "liquid"}]
    assert shown(defn(both, population=pop("BRCA"), scope="report")) == [10, 10, 5]
    assert shown(defn(both, population=pop("BRCA"))) == [10, 10, None]   # the delta rule hides 9


def test_question_17(db):
    c1 = {"id": "c1", "kind": "data", "has": "both_vendors"}
    tmb = lambda cid, vendor: {"id": cid, "kind": "biomarker", "name": "TMB", "vendor": vendor}
    d = defn([c1, tmb("c2", "caris"), tmb("c3", "fmi")], population=pop("MEL"), pivot={"rows": "c2.val", "cols": "c3.val"})
    r = count(d)
    assert r.patients == 17 and any(n.startswith("Patients are linked across vendors") for n in r.notes)
    r = pivot(d)
    assert pcells(r) == {("low", "low"): 7, ("high", "high"): 5, ("high", "low"): 5}
    assert margins(r.row_totals) == {"low": 7, "high": 10} and margins(r.col_totals) == {"low": 12, "high": 5}


def test_question_18(db):
    c1 = alt("c1", ["DNMT3A", "TET2"])
    p = pop("PRAD", assay_class=["liquid"])
    assert shown(defn([c1], population=p)) == [15, 10]
    assert shown(defn([exclude(c1)], population=p)) == [15, 5]


# --- the neighbour check against the differencing attacks -----------------------------------------

def test_attack_exclusion_complement(db):
    d = defn([exclude(alt("c1", ["PIK3CA"])), ihc("c2", "ER")], population=pop("IDC"))
    assert raw_funnel(d) == [30, 25, 9]                    # the funnel rule alone would show 9 ...
    assert shown(defn([ihc("c1", "ER")], population=pop("IDC"))) == [30, 12]   # ... and 12 - 9 is 3 patients
    r = count(d)
    assert steps(r) == [30, 25, None] and r.patients is None
    assert shown(defn([exclude(alt("c1", ["PIK3CA"])), ihc("c2", "ER")], population=pop("ILC"))) == [30, 23, 7]


def test_attack_two_exclusions_together(db):
    d = defn([exclude(alt("c1", ["TP53"])), exclude(alt("c2", ["BRCA1"])), ihc("c3", "ER")], population=pop("HGSOC"))
    assert raw_funnel(d)[-1] == 8
    for one in (apply(d, {"op": "remove_criterion", "id": "c1"}), apply(d, {"op": "remove_criterion", "id": "c2"})):
        assert raw_funnel(one)[-1] == 8                    # a single removal differs by 0 ...
    assert raw_funnel(defn([ihc("c3", "ER")], population=pop("HGSOC")))[-1] == 10   # ... both give 2
    assert steps(count(d))[-1] is None and count(d).patients is None


def exclusion_of_question_10(**kw):
    return defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["STK11", "KEAP1"]))], population=NSCLC, **kw)


def test_attack_exclusion_breakdown_cell(db):
    d = exclusion_of_question_10(breakdown=["sex"])
    raw = raw_count(d)
    assert raw.breakdowns["sex"] == {"male": 5, "female": 8}
    assert raw_count(apply(d, {"op": "remove_criterion", "id": "c2"})).breakdowns["sex"]["male"] == 8
    r = count(d)
    assert r.patients == 13 and cells(r, "sex") == {"male": (None, 8), "female": (None, 24)}   # the line rule hides female


def test_attack_exclusion_pivot_cell(db):
    d = exclusion_of_question_10(pivot={"rows": "sex", "cols": "year"})
    con = queries.get_db()
    try:
        assert queries._run_pivot(con, d).cells[("male", "2024")] == 5
        assert queries._run_pivot(con, apply(d, {"op": "remove_criterion", "id": "c2"})).cells[("male", "2024")] == 8
    finally:
        con.close()
    r = pivot(d)
    assert pcells(r)[("male", "2024")] is None
    for line in line_nones(r):
        assert sum(v is None for v in line) != 1, line


def test_attack_exclude_against_tested_negative(db):
    """exclude minus tested_negative on one gene is the patients with no result for it (a group no include
    query can express)."""
    kras = alt("c1", ["KRAS"])
    d = defn([exclude(kras)], population=pop("GIST"))
    tn = defn([{**kras, "mode": "tested_negative"}], population=pop("GIST"))
    assert raw_funnel(d) == [30, 20] and raw_funnel(tn) == [30, 17]   # 20 - 17 = 3 never tested
    assert count(d).patients == 20 and count(tn).patients is None   # the tested_negative side is the one hidden
    assert [[c.mode for c in n.definition.criteria] for n in neighbours(d)] == [[]]
    assert [[c.mode for c in n.definition.criteria] for n in neighbours(tn)] == [[], ["exclude"]]


def test_attack_union_population(db):
    d = defn([KRAS], population=pop("NSCLC", "PAAD"))
    assert raw_funnel(d) == [42, 29] and raw_funnel(defn([KRAS], population=NSCLC)) == [32, 27]
    r = count(d)
    assert r.patients is None
    assert shown(defn([KRAS], population=NSCLC)) == [32, 27]
    assert shown(defn(population=pop("NSCLC", "PAAD"))) == [42]


def test_attack_union_years(db):
    d = defn([KRAS], population=pop("NSCLC", years=[2024, 2025]))
    assert raw_funnel(d)[-1] == 22
    assert raw_funnel(defn([KRAS], population=pop("NSCLC", years=[2024, 2024])))[-1] == 20
    assert count(d).patients is None


def test_attack_funnel_delta_with_exclusion(db):
    d = defn([exclude(KRAS)], population=pop("PAAD"))
    assert raw_funnel(d) == [10, 8]
    assert _funnel([10, 8]) == [10, None]                  # the funnel rule hides it alone, and the neighbour check agrees
    assert steps(count(d)) == [10, None]


# --- the rule, value by value ----------------------------------------------------------------------

UNIT = defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["TP53"]))], breakdown=["sex"], pivot={"rows": "sex", "cols": "year"})


def raw_pair(**kw):
    """A RawCount for UNIT (everything 'wide apart') and its one neighbour, with `kw` overriding the neighbour."""
    base = dict(funnel=[100, 80], reports=60, by_year={2023: 30, 2024: 30}, year_complete={},
                breakdowns={"sex": {"male": 25, "female": 35}}, denominators={"sex": {"male": 45, "female": 55}})
    here = RawCount(**(base | dict(funnel=[100, 80, 60])))
    here.neighbours = [RawNeighbour(RawCount(**(base | kw)), [0, 1, 1])]
    return here


@pytest.mark.parametrize("delta, hidden", [(0, False), (1, True), (4, True), (5, False), (-3, True), (-5, False)])
def test_neighbour_check_each_value(delta, hidden):
    def result(**kw):
        return suppress.suppress_count(UNIT, raw_pair(**kw))

    # step 1 (80) and step 2 (60) both pair with the neighbour's step 1
    step1 = result(funnel=[100, 80 + delta]).funnel[1].patients
    assert (step1 is None) is hidden
    step2 = result(funnel=[100, 60 + delta]).funnel[2].patients
    assert (step2 is None) is hidden
    assert (result(reports=60 + delta).reports is None) is hidden
    year = {y.year: y.patients for y in result(by_year={2023: 30 + delta, 2024: 30}).by_year}
    assert (year[2023] is None) is hidden
    sex = result(breakdowns={"sex": {"male": 25 + delta, "female": 35}}).breakdowns["sex"]
    assert (next(c for c in sex if c.value == "male").patients is None) is hidden
    sex = result(denominators={"sex": {"male": 45 + delta, "female": 55}}).breakdowns["sex"]
    assert (next(c for c in sex if c.value == "male").denominator is None) is hidden


def test_neighbour_check_absent_key_is_zero():
    r = suppress.suppress_count(UNIT, raw_pair(breakdowns={"sex": {"female": 35}}))
    assert {c.value: c.patients for c in r.breakdowns["sex"]}["male"] is not None   # 25 against absent: far apart
    here = raw_pair(by_year={2024: 30})
    here.by_year = {2023: 3, 2024: 30}
    here.funnel = [100, 80, 60]
    year = {y.year: y.patients for y in suppress.suppress_count(UNIT, here).by_year}
    assert year[2023] is None                               # 3 against absent (0)


def raw_pivot(**kw):
    base = dict(funnel=[100, 80], cells={("a", "x"): 20, ("a", "y"): 30, ("b", "x"): 25, ("b", "y"): 25},
                rows={"a": 50, "b": 50}, cols={"x": 45, "y": 55})
    here = RawPivot(**(base | dict(funnel=[100, 80, 60])))
    here.neighbours = [RawPivotNeighbour(RawPivot(**(base | kw)), [0, 1, 1])]
    return here


@pytest.mark.parametrize("delta, hidden", [(0, False), (1, True), (4, True), (5, False)])
def test_neighbour_check_pivot(delta, hidden):
    def result(**kw):
        return suppress.suppress_pivot(UNIT, raw_pivot(**kw))

    cell = result(cells={("a", "x"): 20 + delta, ("a", "y"): 30, ("b", "x"): 25, ("b", "y"): 25})
    assert (pcells(cell)[("a", "x")] is None) is hidden
    row = result(rows={"a": 50 + delta, "b": 50})
    assert (margins(row.row_totals)["a"] is None) is hidden
    col = result(cols={"x": 45 + delta, "y": 55})
    assert (margins(col.col_totals)["x"] is None) is hidden
    assert (result(funnel=[100, 60 + delta]).patients is None) is hidden


def test_suppress_requires_neighbours():
    bare = RawCount(funnel=[100, 80, 60], reports=60, by_year={}, year_complete={}, breakdowns={}, denominators={})
    with pytest.raises(ValueError, match="neighbours"):
        suppress.suppress_count(UNIT, bare)
    with pytest.raises(ValueError, match="neighbours"):
        suppress.suppress_pivot(UNIT, RawPivot(funnel=[100, 80, 60], cells={}, rows={}, cols={}))
    suppress.suppress_count(defn([KRAS]), RawCount(funnel=[100, 80], reports=60, by_year={}, year_complete={},
                                                    breakdowns={}, denominators={}))   # no neighbours: fine


def test_neighbours():
    c = lambda cid, mode=None: alt(cid, ["KRAS"]) | ({"mode": mode} if mode else {})
    d = defn([c("c1"), c("c2", "exclude"), c("c3"), c("c4", "tested_negative")],
             population={"oncotree": ["A", "B"], "years": [2022, 2024]})
    near = neighbours(d)
    assert len(near) == 3 + 1 + 2 + 2
    assert [[c.id for c in n.definition.criteria] for n in near[:3]] == [["c1", "c3", "c4"], ["c1", "c2", "c3"], ["c1", "c3"]]
    assert [c.mode for c in near[3].definition.criteria] == ["include", "exclude", "include", "exclude"]
    assert near[3].step == [0, 1, 2, 3, 4]
    assert near[0].step == [0, 1, 1, 2, 3]
    assert near[2].step == [0, 1, 1, 2, 2]
    assert [n.definition.population.oncotree for n in near[4:6]] == [["B"], ["A"]]
    assert all(n.step == [0, 1, 2, 3, 4] for n in near[3:])
    assert [n.definition.population.years for n in near[6:]] == [(2023, 2024), (2022, 2023)]
    assert neighbours(defn([c("c1")])) == []
    assert neighbours(defn([c("c1")], population={"oncotree": ["A"], "years": [2022, 2022]})) == []
    big = defn([c("c1", "exclude"), c("c2", "exclude"), c("c3", "exclude")],
               population={"oncotree": [f"T{i}" for i in range(24)], "years": [2020, 2024]})
    assert len(parse(big.model_dump(mode="json", by_alias=True)).criteria) == 3 and data_notes(big)
    with pytest.raises(DefinitionError, match=r"^population: .*33 privacy checks.*at most 32"):
        neighbours(big)
    assert MAX_NEIGHBOURS == 32


def test_count_rejects_too_many_neighbours_before_any_query(db, monkeypatch):
    big = defn([alt(f"c{i}", ["KRAS"], mode="exclude") for i in (1, 2, 3)],
               population={"oncotree": [f"T{i}" for i in range(24)], "years": [2020, 2024]}, pivot={"rows": "year", "cols": "sex"})
    vocabulary()   # build the cached vocabulary first; it opens the file
    monkeypatch.setattr(queries.Vocabulary, "check", lambda self, d: None)
    monkeypatch.setattr(queries, "get_db", lambda: pytest.fail("a query was opened"))
    for call in (count, pivot):
        with pytest.raises(DefinitionError, match="^population: "):
            call(big)


def test_loosen_withheld_with_neighbours(db):
    r = count(defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["STK11"]))], population=pop("PAAD")))
    assert r.patients is None or r.loosen == []
    r = count(defn([exclude(alt("c1", ["PIK3CA"])), ihc("c2", "ER")], population=pop("IDC")))
    assert r.patients is None and r.loosen == [] and r.loosen_offered is False
    seq = {"id": "c1", "kind": "sequence", "first": [{"kind": "data", "has": "tissue"}],
           "then": [{"kind": "data", "has": "liquid"}]}
    assert count(defn([seq])).loosen_offered is True


# --- shapes ----------------------------------------------------------------------------------------

PHASE2_DEFS = [
    exclusion_of_question_10(breakdown=["sex"], pivot={"rows": "sex", "cols": "year"}),
    defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["STK11", "KEAP1"]))], population=NSCLC, scope="report",
         breakdown=["sex"]),
    defn([exclude(alt("c1", ["KRAS", "NRAS"])), exclude(alt("c2", ["BRAF"], aa=["V600E"])),
          alt("c3", ["KRAS"], mode="tested_negative")], population=pop("COADREAD")),
    defn([{"id": "c1", "kind": "sequence", "first": [{"kind": "data", "has": "tissue"}],
           "then": [{"kind": "alteration", "gene": ["ESR1"]}, {"kind": "data", "has": "liquid"}]}]),
    defn([alt("c1", ["ESR1"]), {"id": "c2", "kind": "data", "has": "liquid"}], population=pop("BRCA"), scope="report",
         pivot={"rows": "c1.val", "cols": "year"}),
    defn([{"id": "c1", "kind": "data", "has": "both_vendors"},
          {"id": "c2", "kind": "biomarker", "name": "TMB", "vendor": "caris"},
          {"id": "c3", "kind": "biomarker", "name": "TMB", "vendor": "fmi"}],
         population=pop("MEL"), breakdown=["vendor"], pivot={"rows": "c2.val", "cols": "c3.val"}),
    defn([{"id": "c1", "kind": "data", "has": "serial"}], breakdown=["oncotree"]),
    defn([{"id": "c1", "kind": "data", "has": "wts"}, {"id": "c2", "kind": "data", "has": "liquid", "mode": "exclude"}]),
    defn([KRAS], population=pop("NSCLC", "PAAD"), breakdown=["oncotree"]),
    defn([KRAS], population=pop("NSCLC", years=[2024, 2025]), breakdown=["sex"]),
    defn([exclude(alt("c1", ["PIK3CA"])), ihc("c2", "ER")], population=pop("IDC")),
    defn([exclude(KRAS)], population=pop("PAAD")),
    defn([alt("c1", ["DNMT3A", "TET2"], vendor="caris")], population=pop("PRAD", assay_class=["liquid"]),
         breakdown=["vendor"]),
]


@pytest.mark.parametrize("d", PHASE2_DEFS, ids=range(len(PHASE2_DEFS)))
def test_no_small_numbers_and_no_ids_phase2(db, d):
    vocabulary().check(d)
    results = [count(d)] + ([pivot(d)] if d.pivot else [])
    for result in results:
        for k, v in walk(result.model_dump()):
            assert k not in ("research_id", "report_id", "collected_on")
            assert not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4), (k, v)
            assert not (isinstance(v, str) and v in db["ids"]), (k, v)


def test_compile_phase2_binds_values():
    seq = {"id": "c5", "kind": "sequence", "first": [alt("", ["KRAS"]) | {"id": None, "vendor": "fmi"}],
           "then": [{"kind": "biomarker", "name": "TMB"}, {"kind": "data", "has": "liquid", "vendor": "caris"}]}
    for scope in ("patient", "report"):
        criteria = [alt("c1", ["KRAS", "NRAS"], mode="exclude", vendor="caris"),
                    alt("c2", ["EGFR"], mode="tested_negative", vendor="fmi"),
                    {"id": "c3", "kind": "data", "has": "wts", "vendor": "fmi"},
                    {"id": "c4", "kind": "ihc", "marker": "PD-L1", "vendor": "caris"}]
        if scope == "patient":
            criteria.append(seq)
        d = defn(criteria, scope=scope, pivot={"rows": "c4.val", "cols": "year"})
        for sql, params in (compile(d), compile_pivot(d)):
            for value in ("KRAS", "NRAS", "EGFR", "PD-L1", "caris", "fmi", "TMB"):
                assert value not in sql.replace("'caris'", "").replace("'fmi'", ""), (scope, value)
            flat = [x for v in params.values() for x in (v if isinstance(v, list) else [v])]
            assert {"KRAS", "NRAS", "EGFR", "PD-L1", "caris", "fmi"} <= set(flat)
            assert "$k0_vendor" in sql and "$k1_vendor" in sql


def test_report_scope_has_no_per_patient_state():
    sql, _ = compile(defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["STK11"]))], scope="report"))
    assert "rk AS" in sql and "ANTI JOIN" not in sql
    sql, _ = compile(defn([alt("c1", ["KRAS"]), exclude(alt("c2", ["STK11"]))]))
    assert "ANTI JOIN q1" in sql and "rk AS" not in sql
