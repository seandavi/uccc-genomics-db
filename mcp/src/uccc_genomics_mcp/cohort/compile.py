"""Compile a `Definition` to `(sql, params)` over `mart.report` / `mart.fact`.

Caller values enter only through the params dict (DuckDB `$name` parameters). Everything
interpolated into the SQL text comes from code: parameter and CTE names, and column names that
are validated against `POP_DIMS` / `BREAKDOWN_DIMS` / `PIVOT_DIMS` Literals.
"""
from .definition import (AXIS_RE, BREAKDOWN_DIMS, PIVOT_DIMS, POP_DIMS, REPORT_DATA, Definition,
                         DefinitionError)
from .suppress import MIN_CELL

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
    if leaf.vendor:
        cond += f" AND f.vendor = {bind('vendor', leaf.vendor)}"
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
    if leaf.vendor:
        params[f"{P}_vendor"] = leaf.vendor
        conds = [f"{c} AND f.vendor = ${P}_vendor" for c in conds]
    return conds, params


def _exists(cond: str, alias: str = "p") -> str:
    return ("EXISTS (SELECT 1 FROM mart.fact f WHERE "
            f"f.vendor = {alias}.vendor AND f.report_id = {alias}.report_id AND {cond})")


def _data_pred(leaf, P: str, alias: str = "p") -> tuple[str, dict]:
    """A per-report `data` criterion (wts, liquid, tissue) as a predicate on `mart.report` columns."""
    if leaf.has not in REPORT_DATA:   # both_vendors and serial are per patient and never reach here
        raise DefinitionError(f"data '{leaf.has}' is not a per-report predicate")
    pred = {"wts": f"{alias}.has_wts", "liquid": f"{alias}.assay_class = 'liquid'",
            "tissue": f"{alias}.assay_class = 'tissue'"}[leaf.has]
    params: dict = {}
    if leaf.vendor:
        params[f"{P}_vendor"] = leaf.vendor
        pred += f" AND {alias}.vendor = ${P}_vendor"
    return pred, params


def _leaf_pred(leaf, P: str, alias: str = "p") -> tuple[str, dict]:
    if leaf.kind == "data":
        return _data_pred(leaf, P, alias)
    if leaf.kind == "specimen":
        conds, params = _specimen_conds(leaf, P)
        return " AND ".join(_exists(c, alias) for c in conds), params
    cond, params = _fact_cond(leaf, P)
    return _exists(cond, alias), params


def _members_pred(members, P: str, alias: str) -> tuple[str, dict]:
    """The AND of member predicates, all on the report `alias`; member j has parameter prefix `P`j."""
    parts, params = [], {}
    for j, member in enumerate(members):
        pred, p = _leaf_pred(member, f"{P}{j}", alias)
        parts.append(f"({pred})")
        params |= p
    return " AND ".join(parts), params


def _pred(criterion, i: int, alias: str = "p") -> tuple[str, dict]:
    """The report predicate of one (non-sequence, per-report) criterion."""
    if criterion.kind != "any_of":
        return _leaf_pred(criterion, f"k{i}", alias)
    parts, params = [], {}
    for j, member in enumerate(criterion.of):
        pred, p = _leaf_pred(member, f"k{i}m{j}", alias)
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


def _per_patient(c) -> bool:
    """A `data` criterion that has no report predicate: it is a property of the patient's reports as a set."""
    return c.kind == "data" and c.has not in REPORT_DATA


def _tested_negative_all(i: int, alias: str, vendor: str | None) -> str:
    """The SQL for 'every listed gene of criterion i was reported wild-type or pertinent negative on report `alias`'."""
    return (f"(SELECT count(DISTINCT upper(f.key)) FROM mart.fact f WHERE f.vendor = {alias}.vendor "
            f"AND f.report_id = {alias}.report_id AND f.kind = 'tested_negative' "
            f"AND list_contains($k{i}_gene, upper(f.key))"
            + (f" AND f.vendor = $k{i}_vendor" if vendor else "") + f") = len($k{i}_gene)")


def _from(d: Definition, k: int) -> str:
    """`pp` joined with the first k criteria: include -> JOIN q{i}; exclude -> ANTI JOIN q{i};
    tested_negative -> ANTI JOIN q{i} SEMI JOIN t{i}."""
    sql = "pp"
    for i, c in enumerate(d.criteria[:k]):
        if c.mode == "include":
            sql += f" JOIN q{i} USING (research_id)"
        else:
            sql += f" ANTI JOIN q{i} USING (research_id)"
            if c.mode == "tested_negative":
                sql += f" SEMI JOIN t{i} USING (research_id)"
    return sql


def _patient_ctes(d: Definition, params: dict) -> list[str]:
    ctes = []
    for i, c in enumerate(d.criteria):
        if _per_patient(c):
            if c.has == "both_vendors":
                ctes.append(f"q{i} AS (SELECT research_id, max(y) AS yr FROM (SELECT research_id, vendor, "
                            "min(year) AS y FROM pop GROUP BY 1, 2) GROUP BY 1 HAVING count(*) >= 2)")
            else:
                ctes.append(f"q{i} AS (SELECT research_id, list_sort(list(year) FILTER (WHERE year IS NOT NULL))[2] "
                            "AS yr FROM pop GROUP BY 1 HAVING count(*) >= 2)")
            continue
        if c.kind == "sequence":
            then, p1 = _members_pred(c.then, f"k{i}t", "t")
            first, p2 = _members_pred(c.first, f"k{i}f", "p")
            params |= p1 | p2
            ctes.append(f"m{i} AS (SELECT t.research_id, t.vendor, t.report_id, t.year FROM pop t WHERE {then} "
                        "AND EXISTS (SELECT 1 FROM pop p WHERE p.research_id = t.research_id "
                        f"AND p.collected_on < t.collected_on AND {first}))")
        else:
            pred, p = _pred(c, i)
            params |= p
            ctes.append(f"m{i} AS (SELECT p.research_id, p.vendor, p.report_id, p.year FROM pop p WHERE {pred})")
        ctes.append(f"q{i} AS (SELECT research_id, min(year) AS yr FROM m{i} GROUP BY research_id)")
        if c.mode == "tested_negative":
            ctes.append(f"t{i} AS (SELECT p.research_id FROM pop p JOIN mart.fact f ON f.vendor = p.vendor "
                        "AND f.report_id = p.report_id WHERE f.kind = 'tested_negative' "
                        f"AND list_contains($k{i}_gene, upper(f.key))"
                        + (f" AND f.vendor = $k{i}_vendor" if c.vendor else "")
                        + f" GROUP BY p.research_id HAVING count(DISTINCT upper(f.key)) = len($k{i}_gene))")
    includes = [i for i, c in enumerate(d.criteria) if c.mode == "include"]
    yr = f"greatest({', '.join(f'q{i}.yr' for i in includes)})" if includes else "pp.yr"
    ctes.append(f"cohort AS (SELECT pp.research_id, {yr} AS yr FROM {_from(d, len(d.criteria))})")
    hits = [f"EXISTS (SELECT 1 FROM m{i} WHERE m{i}.vendor = p.vendor AND m{i}.report_id = p.report_id)"
            for i in includes if not _per_patient(d.criteria[i])]
    ctes.append("hit AS (SELECT p.* FROM pop p JOIN cohort USING (research_id)"
                + (f" WHERE {' OR '.join(hits)}" if hits else "") + ")")
    return ctes


def _report_ctes(d: Definition, params: dict) -> list[str]:
    """Every criterion must hold on one report: `rk` has one boolean column per criterion."""
    cols = []
    for i, c in enumerate(d.criteria):
        pred, p = _pred(c, i)
        params |= p
        if c.mode == "include":
            cols.append(f"({pred})")
        else:
            cols.append(f"NOT ({pred})")
            if c.mode == "tested_negative":
                cols[-1] += f" AND {_tested_negative_all(i, 'p', c.vendor)}"
    all_ = " AND ".join(f"rk.k{i}" for i in range(len(cols))) or "true"
    select = "".join(f", {b} AS k{i}" for i, b in enumerate(cols))
    return [f"rk AS (SELECT p.research_id, p.vendor, p.report_id, p.year{select} FROM pop p)",
            f"cohort AS (SELECT research_id, min(year) AS yr FROM rk WHERE {all_} GROUP BY research_id)"
            if cols else "cohort AS (SELECT research_id, yr FROM pp)",
            f"hit AS (SELECT p.* FROM pop p JOIN rk ON rk.vendor = p.vendor AND rk.report_id = p.report_id WHERE {all_})"]


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
        f"assay_class, site_type, has_wts, collected_on FROM mart.report WHERE {' AND '.join(where)})",
        "pp AS (SELECT research_id, min(year) AS yr FROM pop GROUP BY research_id)",
    ]
    ctes += _report_ctes(d, params) if d.scope == "report" else _patient_ctes(d, params)
    return "WITH " + ",\n  ".join(ctes), params


def _funnel_rows(d: Definition, null_cols: str) -> list[str]:
    """One row per funnel step: the patients who met the first k criteria."""
    rows = []
    for k in range(len(d.criteria) + 1):
        if d.scope == "report":
            where = " AND ".join(f"k{i}" for i in range(k)) or "true"
            count = f"SELECT count(DISTINCT research_id) FROM rk WHERE {where}"
        else:
            count = f"SELECT count(*) FROM {_from(d, k)}"
        rows.append(f"SELECT 'funnel', '{k}', {null_cols}, ({count})")
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
        if dim not in BREAKDOWN_DIMS:   # the name goes into the SQL text; models built without validation get here
            raise DefinitionError(f"breakdown: {dim!r} is not a breakdown dimension")
        rows.append(f"SELECT 'breakdown', '{dim}', coalesce({dim}::VARCHAR, 'unknown'), "
                    "count(DISTINCT research_id), NULL FROM hit GROUP BY 3")
        rows.append(f"SELECT 'denominator', '{dim}', coalesce({dim}::VARCHAR, 'unknown'), "
                    "count(DISTINCT research_id), NULL FROM pop GROUP BY 3")
    return ctes + "\n" + "\nUNION ALL ".join(rows), params


def _axis(axis: str, d: Definition) -> tuple[str, str | None, int | None]:
    """('dim', column, None) for a dimension; ('fact', F, criterion position) for `c<n>.F`."""
    m = AXIS_RE.match(axis)
    if m:
        ids = [c.id for c in d.criteria]
        if m[1] not in ids:
            raise DefinitionError(f"pivot: {axis!r} names no criterion")
        return "fact", m[2], ids.index(m[1])
    if axis not in PIVOT_DIMS:   # the name goes into the SQL text
        raise DefinitionError(f"pivot: {axis!r} is not a pivot axis")
    return "dim", axis, None


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
        pv0 = fact_scan(f"h.research_id, coalesce(f.{rf}, 'unknown') AS rv, coalesce(f.{cf}, 'unknown') AS cv", ri)
        extra = [f"pv0 AS ({pv0})"]
    else:
        # A dimension pairs with the same report; two different criteria pair on the same patient.
        on = ("ca.research_id = ra.research_id" if rk == ck == "fact" and d.scope == "patient"
              else "ca.vendor = ra.vendor AND ca.report_id = ra.report_id")
        extra = [f"ra AS ({axis_cte(rk, rf, ri)})", f"ca AS ({axis_cte(ck, cf, ci)})",
                 f"pv0 AS (SELECT ra.research_id, ra.v AS rv, ca.v AS cv FROM ra JOIN ca ON {on})"]

    def label(column: str, kind: str, field: str | None) -> str:
        """`sub` and `val` carry vendor free text that the vocabulary floor keeps out (a rare protein
        change, fusion partner, therapy name, trial id): a value held by fewer than MIN_CELL patients
        becomes 'other'. A dimension value or a `key` is already a vocabulary value the caller chose."""
        if kind == "dim" or field == "key":
            return column
        return (f"CASE WHEN {column} IN (SELECT {column} FROM pv0 GROUP BY {column} "
                f"HAVING count(DISTINCT research_id) >= {MIN_CELL}) THEN {column} ELSE 'other' END")

    # Margins count the same (patient, row, col) set as the cells, so every patient in a margin is in a cell of that line.
    extra.append(f"pv AS (SELECT research_id, {label('rv', rk, rf)} AS rv, {label('cv', ck, cf)} AS cv FROM pv0)")
    rows = [
        "SELECT 'cell' AS section, rv AS r, cv AS c, count(DISTINCT research_id) AS patients FROM pv GROUP BY rv, cv",
        "SELECT 'row', rv, NULL, count(DISTINCT research_id) FROM pv GROUP BY rv",
        "SELECT 'col', NULL, cv, count(DISTINCT research_id) FROM pv GROUP BY cv",
    ] + _funnel_rows(d, "NULL")
    return ctes + ",\n  " + ",\n  ".join(extra) + "\n" + "\nUNION ALL ".join(rows), params
