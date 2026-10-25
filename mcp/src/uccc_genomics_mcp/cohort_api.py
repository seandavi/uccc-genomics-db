"""Cohort feasibility API: floored patient counts for a fixed set of filters (dashboard/COHORT_TOOL.md).

No SQL from the client: every parameter is an allow-list of vocabulary values read from the DB,
and values enter the one query below only as named parameters. Every count leaves through
`suppress`, which runs last on the response dict.
"""
import argparse
import json
import os
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

import uccc_genomics.config  # noqa: F401  loads the repo .env (ACCESS_TEAM, ACCESS_AUD, COHORT_ROUND)
from uccc_genomics_mcp import authen
from uccc_genomics_mcp.cohort.suppress import MIN_CELL, floor
from uccc_genomics_mcp.server import DEID_DB, get_db

COUNT_KEYS = ("patients", "reports", "tested")
LIST_PARAMS = ("disease", "organ", "sex", "age", "vendor", "assay_class", "gene", "alt_class", "aa")
AGE_BANDS = ["<50", "50-64", "65-74", "75+", "unknown"]
ALT_CLASSES = ["pathogenic", "vus", "unclassified", "amplification", "loss", "fusion"]
OPT_IN_CLASSES = ("vus", "unclassified")
AGE_COVERS = "Age is known for Caris tissue reports only; everything else is 'unknown'."

# One row per report, with the filterable attributes. Age comes from the Caris tumor specimen and
# only for tissue reports: every Caris liquid specimen carries a sentinel the de-id cap turns into 89.
REP = """
rep AS (
  SELECT r.vendor, r.report_id, r.research_id, r.disease_text AS disease, r.organ_system AS organ,
         lower(r.gender) AS sex, r.assay_class, year(r.collected_on) AS year,
         CASE WHEN a.age IS NULL THEN 'unknown' WHEN a.age < 50 THEN '<50' WHEN a.age < 65 THEN '50-64'
              WHEN a.age < 75 THEN '65-74' ELSE '75+' END AS age
  FROM unified.report r
  LEFT JOIN (SELECT case_id, max(age_at_collection) AS age FROM caris.specimen
             WHERE specimen_kind = 'tumor' GROUP BY 1) a
         ON r.vendor = 'caris' AND r.assay_class = 'tissue' AND a.case_id = r.report_id
)"""

# One row per (report, gene, class, protein change): dashboard/src/data/cohort.json.py's ALT union
# with VUS and unclassified as their own classes (pathogenic merges the pathogenic and likely
# pathogenic tiers; benign never enters) and `p.` stripped so Caris and FMI spellings meet.
ALT = """
alt AS (
  SELECT vendor, report_id, gene,
         CASE WHEN tier IN ('pathogenic', 'likely_pathogenic') THEN 'pathogenic' ELSE tier END AS alt_class,
         regexp_replace(hgvs_p, '^p\\.', '') AS aa
  FROM unified.variant
  WHERE tier IN ('pathogenic', 'likely_pathogenic', 'vus', 'unclassified')
    AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene, cn_type, NULL FROM unified.cna
    WHERE cn_type IN ('amplification', 'loss') AND gene IS NOT NULL AND gene NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene1, 'fusion', NULL FROM unified.fusion WHERE gene1 IS NOT NULL AND gene1 NOT IN ('N/A', '')
  UNION ALL SELECT vendor, report_id, gene2, 'fusion', NULL FROM unified.fusion
    WHERE gene2 IS NOT NULL AND gene2 <> gene1 AND gene2 NOT IN ('N/A', '')
)"""


def _in(name, col):
    return f"(${name}::VARCHAR[] IS NULL OR list_contains(${name}::VARCHAR[], {col}))"


COHORT_SQL = f"""
WITH {REP}, {ALT},
base AS (
  SELECT * FROM rep
  WHERE {_in('disease', 'disease')} AND {_in('organ', 'organ')} AND {_in('sex', 'sex')} AND {_in('age', 'age')}
    AND {_in('vendor', 'vendor')} AND {_in('assay_class', 'assay_class')}
    AND ($year_from::INT IS NULL OR year >= $year_from::INT) AND ($year_to::INT IS NULL OR year <= $year_to::INT)
),
match AS (
  SELECT DISTINCT a.vendor, a.report_id, a.alt_class FROM alt a
  WHERE list_contains($gene::VARCHAR[], a.gene) AND list_contains($alt_class::VARCHAR[], a.alt_class)
    AND {_in('aa', 'a.aa')}
),
hit AS (
  SELECT * FROM base b
  WHERE $gene::VARCHAR[] IS NULL OR EXISTS (SELECT 1 FROM match m WHERE m.vendor = b.vendor AND m.report_id = b.report_id)
),
first AS (SELECT research_id, min(year) AS year FROM hit GROUP BY 1)
SELECT 'total' AS dim, NULL AS v1, NULL AS v2, count(DISTINCT research_id) AS patients, count(*) AS reports FROM hit
UNION ALL SELECT 'tested', NULL, NULL, count(DISTINCT research_id), count(*) FROM base
UNION ALL SELECT 'year', year::VARCHAR, NULL, count(*), NULL FROM first WHERE year IS NOT NULL GROUP BY 2
UNION ALL SELECT 'disease', disease, NULL, count(DISTINCT research_id), NULL FROM hit GROUP BY 2
UNION ALL SELECT 'vendor_class', vendor, assay_class, count(DISTINCT research_id), NULL FROM hit GROUP BY 2, 3
UNION ALL SELECT 'sex', sex, NULL, count(DISTINCT research_id), NULL FROM hit GROUP BY 2
UNION ALL SELECT 'age', age, NULL, count(DISTINCT research_id), NULL FROM hit GROUP BY 2
UNION ALL SELECT 'alt_class', m.alt_class, NULL, count(DISTINCT h.research_id), NULL
  FROM hit h JOIN match m ON m.vendor = h.vendor AND m.report_id = h.report_id GROUP BY 2
"""

# Vocabularies are floored like counts: a value with under MIN_CELL patients could only ever
# return "<5" on its own, and OR-ing it with a larger value would reveal it by differencing.
VOCAB_SQL = f"""
WITH {REP}, {ALT},
pa AS (SELECT DISTINCT r.research_id, a.gene, a.aa FROM alt a JOIN rep r USING (vendor, report_id))
SELECT 'disease', disease, NULL FROM rep GROUP BY 2 HAVING count(DISTINCT research_id) >= {MIN_CELL}
UNION ALL SELECT 'organ', organ, NULL FROM rep GROUP BY 2 HAVING count(DISTINCT research_id) >= {MIN_CELL}
UNION ALL SELECT 'gene', gene, NULL FROM pa GROUP BY 2 HAVING count(DISTINCT research_id) >= {MIN_CELL}
UNION ALL SELECT 'aa', gene, aa FROM pa WHERE aa IS NOT NULL GROUP BY 2, 3 HAVING count(DISTINCT research_id) >= {MIN_CELL}
UNION ALL SELECT 'year', min(year)::VARCHAR, max(year)::VARCHAR FROM rep
"""

_vocab = {"mtime": None}


def vocab():
    """Allow-lists for every parameter, most frequent first; reloaded when the daily rebuild replaces the file."""
    mtime = os.path.getmtime(DEID_DB) if os.path.exists(DEID_DB) else 0
    if _vocab["mtime"] != mtime:
        con = get_db()
        try:
            rows = con.execute(VOCAB_SQL).fetchall()
        finally:
            con.close()
        v = {"disease": [], "organ": [], "gene": [], "aa": {}}
        for dim, a, b in rows:
            if dim == "aa":
                v["aa"].setdefault(a, []).append(b)
            elif dim == "year":
                v["year_min"], v["year_max"] = int(a), int(b)
            else:
                v[dim].append(a)
        for k in ("disease", "organ", "gene"):
            v[k].sort()
        for k in v["aa"]:
            v["aa"][k].sort()
        v |= {"sex": ["female", "male"], "age": AGE_BANDS, "vendor": ["caris", "fmi"],
              "assay_class": ["tissue", "liquid", "heme"], "alt_class": ALT_CLASSES}
        _vocab.update(mtime=mtime, v=v)
    return _vocab["v"]


class BadRequest(ValueError):
    pass


def parse(query_params, v) -> dict:
    """Request query string -> named SQL parameters, or BadRequest naming the offending parameter."""
    unknown = set(query_params.keys()) - set(LIST_PARAMS) - {"year_from", "year_to"}
    if unknown:
        raise BadRequest(f"unknown parameter: {sorted(unknown)[0]}")
    p = {}
    for name in LIST_PARAMS:
        vals = query_params.getlist(name)
        allowed = v["aa"].get(p["gene"][0], []) if name == "aa" and p.get("gene") else v.get(name, [])
        if name == "aa" and vals and len(p.get("gene") or []) != 1:
            raise BadRequest("aa: needs exactly one gene")
        if name == "alt_class" and vals and not p.get("gene"):
            raise BadRequest("alt_class: needs a gene")
        for x in vals:
            if x not in allowed:
                raise BadRequest(f"{name}: {x!r} is not in the vocabulary")
        p[name] = sorted(set(vals)) or None
    if p["gene"] and not p["alt_class"]:
        p["alt_class"] = [c for c in ALT_CLASSES if c not in OPT_IN_CLASSES]
    for name in ("year_from", "year_to"):
        x = query_params.get(name)
        if x is not None and not (x.isdigit() and v["year_min"] <= int(x) <= v["year_max"]):
            raise BadRequest(f"{name}: must be a year from {v['year_min']} to {v['year_max']}")
        p[name] = int(x) if x is not None else None
    return p


def run(p: dict) -> dict:
    """The unsuppressed answer. Never returned as-is: `respond` passes it through `suppress`."""
    con = get_db()
    try:
        rows = con.execute(COHORT_SQL, p).fetchall()
    finally:
        con.close()
    out = {"by_year": [], "by_disease": [], "by_vendor_class": [], "by_sex": [], "by_age": [], "by_alt_class": []}
    for dim, v1, v2, patients, reports in rows:
        if dim == "total":
            out |= {"patients": patients, "reports": reports}
        elif dim == "tested":
            out["tested"] = patients
        elif dim == "year":
            out["by_year"].append({"year": int(v1), "patients": patients})
        elif dim == "vendor_class":
            out["by_vendor_class"].append({"vendor": v1, "assay_class": v2, "patients": patients})
        else:
            out[f"by_{dim}"].append({dim: v1, "patients": patients})
    out["by_year"].sort(key=lambda r: r["year"])
    for k in ("by_disease", "by_vendor_class", "by_sex", "by_age", "by_alt_class"):
        out[k].sort(key=lambda r: -r["patients"])
    return out


def suppress(out: dict) -> dict:
    """Primary floor on every count, secondary suppression in each list, whole-cohort rule."""
    out = {k: floor(v) if k in COUNT_KEYS else v for k, v in out.items()}
    for k, cells in out.items():
        if not k.startswith("by_"):
            continue
        cells = [{**c, "patients": floor(c["patients"])} for c in cells]
        # One hidden cell next to a shown total could be recovered as total minus the rest.
        if sum(c["patients"] is None for c in cells) == 1:
            shown = [c for c in cells if c["patients"] is not None]
            if shown:
                min(shown, key=lambda c: c["patients"])["patients"] = None
        out[k] = cells if out.get("patients") is not None else []
    return out | {"meta": {"min_cell": MIN_CELL, "age_covers": AGE_COVERS}}


# --- HTTP -------------------------------------------------------------------------------------

def authed(request: Request):
    """The caller's email, or a 401 response to return instead."""
    try:
        return authen.user(request), None
    except PermissionError as e:
        return None, JSONResponse({"error": str(e)}, status_code=401, headers=authen.challenge())


def audit(email, params, patients):
    print(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "email": email,
                      "params": {k: v for k, v in params.items() if v is not None}, "patients": patients}), flush=True)


def cohort(request: Request):
    email, denied = authed(request)
    if denied:
        return denied
    try:
        p = parse(request.query_params, vocab())
    except BadRequest as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    out = run(p)
    audit(email, p, out["patients"])
    return JSONResponse(suppress(out))


def options(request: Request):
    _, denied = authed(request)
    if denied:
        return denied
    v = vocab()
    return JSONResponse({k: v[k] for k in v} | {"min_cell": MIN_CELL})


def health(request: Request):
    """OBSERVABILITY.md contract: 200 with "Healthy" only if the DB opens and answers."""
    try:
        con = get_db()
        try:
            n = con.execute("SELECT count(*) FROM unified.report").fetchone()[0]
        finally:
            con.close()
        return JSONResponse({"status": "Healthy", "reports": n})
    except Exception as e:
        return JSONResponse({"status": "unhealthy", "error": str(e)}, status_code=503)


def app(static_dir=None):
    routes = [Route("/api/cohort", cohort), Route("/api/options", options), Route("/api/health", health)]
    if static_dir:  # local dev only: serve the built dashboard same-origin, as the Worker does in production
        from starlette.staticfiles import StaticFiles
        routes.append(Mount("/", StaticFiles(directory=static_dir, html=True)))
    return Starlette(routes=routes)


def main(argv=None):
    ap = argparse.ArgumentParser(description="UCCC cohort feasibility API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--auth", choices=authen.MODES, default="access",
                    help="access: Cloudflare Access JWT (production); password: one local account; none: local dev only")
    ap.add_argument("--static", help="also serve this built dashboard directory at / (local dev only)")
    args = ap.parse_args(argv)
    authen.configure(args.auth)
    uvicorn.run(app(args.static), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
