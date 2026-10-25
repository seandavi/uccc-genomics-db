"""Compile a `Definition` to `(sql, params)` over `mart.report` / `mart.fact`.

Caller values enter only through the params dict (DuckDB `$name` parameters). Everything
interpolated into the SQL text comes from code: parameter and CTE names, and column names that
are validated against `POP_DIMS` / `BREAKDOWN_DIMS` / `PIVOT_DIMS` Literals.
"""
from .definition import AXIS_RE, POP_DIMS, Definition, DefinitionError

_FUNNEL_COLS = "section, dim, value, patients, flag"


def _fact_cond(leaf, P: str) -> tuple[str, dict]:
    """The `mart.fact f` condition for one non-specimen leaf; `P` is its parameter prefix."""
    params: dict = {}

    def bind(name: str, value):
        params[f"{P}_{name}"] = value
        return f"${P}_{name}"

    match leaf.kind:
        case "alteration":
            cond = f"f.kind = 'alteration' AND list_contains({bind('gene', leaf.gene)}, upper(f.key))"
            if leaf.class_:
                cond += f" AND list_contains({bind('class', leaf.class_)}, f.sub)"
            if leaf.aa:
                cond += f" AND f.sub = 'mutation' AND list_contains({bind('aa', leaf.aa)}, f.val)"
            cond += f" AND (f.sub <> 'mutation' OR list_contains({bind('tier', leaf.tier)}, f.tier))"
        case "biomarker":
            cond = f"f.kind = 'biomarker' AND f.key = {bind('name', leaf.name)}"
            if leaf.call:
                cond += f" AND list_contains({bind('call', leaf.call)}, f.val)"
            if leaf.at_least is not None:
                cond += f" AND f.num >= {bind('at_least', leaf.at_least)}"
        case "ihc":
            cond = f"f.kind = 'ihc' AND f.key = {bind('marker', leaf.marker)}"
            if leaf.clone:
                cond += f" AND f.sub = {bind('clone', leaf.clone)}"
            if leaf.call:
                cond += f" AND list_contains({bind('call', leaf.call)}, f.val)"
            if leaf.measure:
                cond += f" AND f.unit = {bind('measure', leaf.measure)}"
            if leaf.at_least is not None:
                cond += f" AND f.num >= {bind('at_least', leaf.at_least)}"
        case "expression":
            cond = f"f.kind = 'expression' AND list_contains({bind('gene', leaf.gene)}, upper(f.key))"
            if leaf.percentile_at_least is not None:
                cond += f" AND f.num >= {bind('pct', leaf.percentile_at_least)}"
        case "actionability":
            cond = f"f.kind = 'actionability' AND list_contains({bind('evidence', leaf.evidence)}, f.key)"
        case _:
            raise DefinitionError(f"no fact condition for kind '{leaf.kind}'")
    return cond, params


def _specimen_conds(leaf, P: str) -> tuple[list[str], dict]:
    """One condition per specimen field that is set: each is its own fact row."""
    conds, params = [], {}
    for name, key in (("site_type", "site_type"), ("site", "site")):
        if getattr(leaf, name):
            params[f"{P}_{name}"] = getattr(leaf, name)
            conds.append(f"f.kind = 'specimen' AND f.key = '{key}' AND list_contains(${P}_{name}, f.val)")
    if leaf.purity_at_least is not None:
        params[f"{P}_purity"] = leaf.purity_at_least
        conds.append(f"f.kind = 'specimen' AND f.key = 'purity' AND f.num >= ${P}_purity")
    return conds, params


def _exists(cond: str) -> str:
    return ("EXISTS (SELECT 1 FROM mart.fact f WHERE f.vendor = p.vendor AND f.report_id = p.report_id "
            f"AND {cond})")


def _leaf_pred(leaf, P: str) -> tuple[str, dict]:
    if leaf.kind == "specimen":
        conds, params = _specimen_conds(leaf, P)
        return " AND ".join(_exists(c) for c in conds), params
    cond, params = _fact_cond(leaf, P)
    return _exists(cond), params


def _pred(criterion, i: int) -> tuple[str, dict]:
    if criterion.kind != "any_of":
        return _leaf_pred(criterion, f"k{i}")
    parts, params = [], {}
    for j, member in enumerate(criterion.of):
        pred, p = _leaf_pred(member, f"k{i}m{j}")
        parts.append(f"({pred})")
        params |= p
    return "(" + " OR ".join(parts) + ")", params


def _criterion_cond(criterion, i: int) -> tuple[str, dict]:
    """The fact condition (not specimen) a pivot axis on criterion `i` scans."""
    if criterion.kind != "any_of":
        return _fact_cond(criterion, f"k{i}")
    parts, params = [], {}
    for j, member in enumerate(criterion.of):
        cond, p = _fact_cond(member, f"k{i}m{j}")
        parts.append(f"({cond})")
        params |= p
    return "(" + " OR ".join(parts) + ")", params


def _ctes(d: Definition) -> tuple[str, dict]:
    params: dict = {}
    where = ["true"]
    for dim in POP_DIMS:
        values = getattr(d.population, dim)
        if values:
            params[f"pop_{dim}"] = values
            where.append(f"list_contains($pop_{dim}, {dim})")
    if d.population.years is not None:
        params["pop_year_from"], params["pop_year_to"] = d.population.years
        where.append("year BETWEEN $pop_year_from AND $pop_year_to")
    ctes = [
        "pop AS (SELECT research_id, vendor, report_id, year, year_complete, oncotree, organ, sex, age_band, "
        f"assay_class, site_type, has_wts FROM mart.report WHERE {' AND '.join(where)})",
        "pp AS (SELECT research_id, min(year) AS yr FROM pop GROUP BY research_id)",
    ]
    n = len(d.criteria)
    for i, c in enumerate(d.criteria):
        pred, p = _pred(c, i)
        params |= p
        ctes.append(f"m{i} AS (SELECT p.research_id, p.vendor, p.report_id, p.year FROM pop p WHERE {pred})")
        ctes.append(f"q{i} AS (SELECT research_id, min(year) AS yr FROM m{i} GROUP BY research_id)")
    if n:
        joins = "".join(f" JOIN q{i} USING (research_id)" for i in range(n))
        yr = ", ".join(f"q{i}.yr" for i in range(n))
        ctes.append(f"cohort AS (SELECT pp.research_id, greatest({yr}) AS yr FROM pp{joins})")
        hit = " OR ".join(f"EXISTS (SELECT 1 FROM m{i} WHERE m{i}.vendor = p.vendor AND m{i}.report_id = p.report_id)"
                          for i in range(n))
        ctes.append(f"hit AS (SELECT p.* FROM pop p JOIN cohort USING (research_id) WHERE {hit})")
    else:
        ctes.append("cohort AS (SELECT research_id, yr FROM pp)")
        ctes.append("hit AS (SELECT * FROM pop)")
    return "WITH " + ",\n  ".join(ctes), params


def _funnel_rows(d: Definition, null_cols: str) -> list[str]:
    """One row per funnel step: the patients who met the first k criteria."""
    rows = []
    for k in range(len(d.criteria) + 1):
        joins = "".join(f" JOIN q{i} USING (research_id)" for i in range(k))
        rows.append(f"SELECT 'funnel', '{k}', {null_cols}, (SELECT count(*) FROM pp{joins})")
    return rows


def compile(d: Definition) -> tuple[str, dict]:
    """The count statement: funnel, reports, by-year, breakdown and denominator rows as
    (section, dim, value, patients, flag)."""
    ctes, params = _ctes(d)
    rows = ["SELECT 'funnel' AS section, '0' AS dim, NULL::VARCHAR AS value, "
            "(SELECT count(*) FROM pp) AS patients, NULL::BOOLEAN AS flag"]
    rows += [r + ", NULL" for r in _funnel_rows(d, "NULL")[1:]]
    rows += [
        "SELECT 'reports', NULL, NULL, (SELECT count(*) FROM hit), NULL",
        "SELECT 'year', NULL, yr::VARCHAR, count(*), NULL FROM cohort WHERE yr IS NOT NULL GROUP BY yr",
        "SELECT 'year_complete', NULL, year::VARCHAR, NULL, bool_and(year_complete) FROM pop "
        "WHERE year IS NOT NULL GROUP BY year",
    ]
    for dim in d.breakdown:
        rows.append(f"SELECT 'breakdown', '{dim}', coalesce({dim}::VARCHAR, 'unknown'), "
                    "count(DISTINCT research_id), NULL FROM hit GROUP BY 3")
        rows.append(f"SELECT 'denominator', '{dim}', coalesce({dim}::VARCHAR, 'unknown'), "
                    "count(DISTINCT research_id), NULL FROM pop GROUP BY 3")
    return ctes + "\n" + "\nUNION ALL ".join(rows), params


def _axis(axis: str, d: Definition) -> tuple[str, str | None, int | None]:
    """('dim', column, None) for a dimension; ('fact', F, criterion position) for `c<n>.F`."""
    m = AXIS_RE.match(axis)
    if not m:
        return "dim", axis, None
    return "fact", m[2], next(i for i, c in enumerate(d.criteria) if c.id == m[1])


def compile_pivot(d: Definition) -> tuple[str, dict]:
    """The pivot statement: ('cell', row, col, patients), ('row', value, NULL, patients),
    ('col', NULL, value, patients) and the funnel rows. Needs `d.pivot`."""
    if d.pivot is None:
        raise DefinitionError("pivot: the definition has no pivot")
    ctes, params = _ctes(d)
    (rk, rf, ri), (ck, cf, ci) = _axis(d.pivot.rows, d), _axis(d.pivot.cols, d)

    def fact_scan(select: str, i: int) -> str:
        cond, p = _criterion_cond(d.criteria[i], i)
        params.update(p)
        return (f"SELECT DISTINCT {select} FROM hit h JOIN mart.fact f "
                f"ON f.vendor = h.vendor AND f.report_id = h.report_id WHERE {cond}")

    def axis_cte(kind: str, field: str, i: int | None) -> str:
        if kind == "dim":
            return f"SELECT DISTINCT research_id, vendor, report_id, coalesce({field}::VARCHAR, 'unknown') AS v FROM hit"
        return fact_scan(f"h.research_id, h.vendor, h.report_id, coalesce(f.{field}, 'unknown') AS v", i)

    if rk == ck == "fact" and ri == ci:
        pv = fact_scan(f"h.research_id, coalesce(f.{rf}, 'unknown') AS rv, coalesce(f.{cf}, 'unknown') AS cv", ri)
        extra = [f"pv AS ({pv})", "ra AS (SELECT research_id, rv AS v FROM pv)",
                 "ca AS (SELECT research_id, cv AS v FROM pv)"]
    else:
        # A dimension pairs with the same report; two different criteria pair on the same patient.
        on = ("ca.research_id = ra.research_id" if rk == ck == "fact"
              else "ca.vendor = ra.vendor AND ca.report_id = ra.report_id")
        extra = [f"ra AS ({axis_cte(rk, rf, ri)})", f"ca AS ({axis_cte(ck, cf, ci)})",
                 f"pv AS (SELECT ra.research_id, ra.v AS rv, ca.v AS cv FROM ra JOIN ca ON {on})"]
    rows = [
        "SELECT 'cell' AS section, rv AS r, cv AS c, count(DISTINCT research_id) AS patients FROM pv GROUP BY rv, cv",
        "SELECT 'row', v, NULL, count(DISTINCT research_id) FROM ra GROUP BY v",
        "SELECT 'col', NULL, v, count(DISTINCT research_id) FROM ca GROUP BY v",
    ] + _funnel_rows(d, "NULL")
    return ctes + ",\n  " + ",\n  ".join(extra) + "\n" + "\nUNION ALL ".join(rows), params
