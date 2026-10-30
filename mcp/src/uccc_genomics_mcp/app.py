"""genomics-app: REST (/api/*) and MCP (/mcp) over the cohort module, behind authen (docs/specs/35-*.md).

One process, two surfaces, one set of shared calls (`run_*`): the routes and tools add only
transport and error mapping. Every number comes out of `cohort.count` / `cohort.pivot`, already
suppressed; nothing here post-processes counts. `RequireUser` authenticates every request but the open
routes (/api/health, /api/public/summary, the landing page /, /assets/* and, under --auth authentik, the
/auth/* sign-in endpoints), once, outside FastAPI and the MCP SDK, then refuses a signed-in user who has not
accepted the current portal terms (`terms.py`): the terms page for a browser navigation, 403 for /api/* and
/mcp; only `POST /api/terms/accept` is exempt.
"""
import argparse
import collections
import json
import math
import os
import posixpath
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

import uccc_genomics.config  # noqa: F401  loads the repo .env (APP_USER, APP_PASSWORD_HASH, ACCESS_*)
from uccc_genomics_mcp import authen, broker, cohort, public, saved, terms
from uccc_genomics_mcp.cohort import CountResult, Definition, DefinitionError, Operation, PivotResult
from uccc_genomics_mcp.cohort.vocabulary import FIELDS
from uccc_genomics_mcp.broker import Irb, IrbList, MyRequestDetail, RequestDetail, Requests, RequestStatus
from uccc_genomics_mcp.saved import (CohortVersion, Deleted, History, SavedCohort, SavedList, Snapshot,
                                     Snapshots)
from uccc_genomics_mcp.server import get_db

Surface = Literal["rest", "mcp"]

INSTRUCTIONS = (
    "Build a cohort definition (its JSON Schema comes from describe_definition), edit it with apply_op, map "
    "the user's words to vocabulary values with search_vocabulary, then count it, or pivot it once its pivot "
    "is set. patients, denominator, the funnel and years count distinct patients across Caris and FMI (a "
    "patient with reports from both vendors counts once). A breakdown or pivot cell counts the patients with "
    "a report having that value, so one patient can be in several cells and cells need not add up to "
    "patients. reports counts the cohort patients' in-population reports (Caris and FMI) that match at least "
    "one include criterion (an exclude, tested_negative, both_vendors or serial criterion never makes a report "
    "count), or all of them when no criterion can; with scope 'report', the reports on which every criterion "
    "holds; it is not a patient count. null means suppressed (1-4, or recoverable by subtraction), never zero. "
    "A criterion's mode is include (default), exclude or tested_negative; scope 'report' makes every criterion "
    "match on one report. A count can also be null because it differs by 1-4 from the same cohort one edit "
    "away: without an exclusion, with a tested_negative criterion as a plain exclude, without one listed "
    "population value or one end year of a year range, or at patient scope instead of report scope (the "
    "result's notes say so). Then loosen_offered is false: loosen suggestions were not computed, so an empty "
    "loosen does not mean that no single criterion would help. "
    "Quote only numbers a tool returned. Never claim the data holds stage, treatment, outcomes, race or ethnicity. Saved cohorts belong to the "
    "logged-in user: save_cohort, then edit with apply_saved_op (each edit is a new revision; "
    "revert_saved_cohort undoes). Saved cohorts hold no counts; count the head definition. Snapshots store "
    "the suppressed count with its data date for grant text. "
    "Requests for identified data are read-only here: list_my_requests and get_my_request show the caller's own; "
    "the broker_* tools are for the honest broker group only. "
    "A 403 saying the portal terms are not accepted means the user must open /discover in a browser and "
    "accept them; tools can't do it.")


# --- auth ----------------------------------------------------------------------------------------

PUBLIC_PATHS = ("/api/health", "/api/public/summary", "/")   # open under every --auth mode


def public_path(path: str) -> bool:
    """True for the routes anyone may call: health, the public summary, the landing page and the
    built assets (hashed JS/CSS from the public repo; no data). normpath first, so
    /assets/../discover.html is not an asset."""
    return path in PUBLIC_PATHS or posixpath.normpath(path).startswith("/assets/")


class RequireUser:
    """Pure ASGI middleware around the whole app: every HTTP request except the open routes
    (/api/health, /api/public/summary, /, /assets/*) and the open sign-in paths (/auth/*, authentik only)
    is authenticated once with authen.user(); the authen.User goes into the request's
    scope state. A failed browser navigation to the static site gets the sign-in page (authen.signin_page,
    which keeps the #fragment); /api/* and /mcp answer 401; a Bearer token that can't be checked because the
    provider is unreachable gets 503. A signed-in user who hasn't accepted the current portal terms gets the
    terms page (browser GET of a non-/api, non-/mcp path) or 403 {"detail": terms.TERMS_REQUIRED}, except on
    terms.ACCEPT_PATH; with no database the gate fails closed (503) under --auth access|authentik and is off
    under --auth none|password (terms.gate_on)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or (scope["type"] == "http" and (
                public_path(scope["path"]) or authen.open_path(scope["path"]))):
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":   # no websocket routes
            return
        try:   # scrypt and the JWKS fetch block
            u = await run_in_threadpool(authen.user, Request(scope))
        except PermissionError as e:
            path, login = scope["path"], authen.login_path()
            if isinstance(e, authen.ProviderUnavailable):   # a Bearer token we couldn't check: not the caller's fault
                response = JSONResponse({"detail": str(e)}, status_code=503,
                                        headers={"Retry-After": str(authen.PROVIDER_RETRY_SECONDS)})
            elif login and scope["method"] == "GET" and not path.startswith("/api/") and path != "/mcp":
                response = authen.signin_page()
            else:
                response = JSONResponse({"detail": str(e)} | ({"login": login} if login else {}), status_code=401,
                                        headers=authen.challenge())
            await response(scope, receive, send)
            return
        scope["state"] = {**scope.get("state", {}), "user": u}   # a fresh dict per request
        path = scope["path"]
        if not (path == terms.ACCEPT_PATH and scope["method"] == "POST") and terms.gate_on():
            try:
                ok = await terms.accepted(u.sub)
            except saved.Unavailable as e:   # --auth access|authentik built without a database: closed
                await JSONResponse({"detail": "portal terms acceptance needs a database (DATABASE_URL)"},
                                   status_code=503)(scope, receive, send)
                return
            if not ok:
                if scope["method"] == "GET" and not path.startswith("/api/") and path != "/mcp":
                    response = terms.page(sign_out=authen.AUTH["mode"] == "authentik")
                else:
                    response = JSONResponse({"detail": terms.TERMS_REQUIRED}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def user(request: Request) -> authen.User:
    """FastAPI dependency: the User RequireUser stored; HTTPException(401) if it is missing."""
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "not authenticated", headers=authen.challenge())
    return u


def _mcp_user(ctx: Context) -> authen.User:
    """The User RequireUser stored for this MCP POST; ToolError if there is no HTTP request or
    no user (an in-process call that bypassed the middleware)."""
    try:
        return ctx.request_context.request.state.user
    except (ValueError, AttributeError):
        raise ToolError("not authenticated") from None


def broker_user(u: authen.User = Depends(user)) -> authen.User:
    """FastAPI dependency: the honest broker group only (403 otherwise)."""
    if not u.broker:
        raise HTTPException(403, "honest broker only")
    return u


def _mcp_broker(ctx: Context) -> authen.User:
    u = _mcp_user(ctx)
    if not u.broker:
        raise ToolError("honest broker only")
    return u


# --- models --------------------------------------------------------------------------------------

class ApplyRequest(BaseModel):
    definition: Definition
    op: Operation


class ApplyResult(BaseModel):
    definition: Definition
    cohort_id: str


class SavedApplyRequest(BaseModel):
    op: Operation


class RevertRequest(BaseModel):
    to: int = Field(ge=1)


class Option(BaseModel):
    field: str            # VocabEntry.field, e.g. "alteration.gene"
    parent: str | None
    value: str


FIELD_HELP = ("Only this vocabulary field's values (q may then be empty); one of "
              + ", ".join(FIELDS) + ". Any other value is a 400.")


class Options(BaseModel):
    entries: list[Option]
    years: tuple[int, int] | None
    cut_points: dict[str, list[float]]
    min_cell: int


class Me(BaseModel):
    sub: str
    email: str
    sign_out: bool   # true under --auth authentik: Discover shows "Sign out"


class TermsAccept(BaseModel):
    version: str = Field(max_length=64)   # the TERMS_VERSION the page showed


class SchemaInfo(BaseModel):
    version: int
    definition: dict
    operation: dict
    cut_points: dict[str, list[float]]
    min_cell: int


# --- rate limit and audit ------------------------------------------------------------------------

RATE_LIMIT = 60        # count + pivot calls per user per RATE_WINDOW, REST and MCP together
RATE_WINDOW = 60.0     # seconds
# ponytail: in-process, per user, reset on restart; per-process limits multiply with more than one
# worker. Move to Postgres (saved.py's database) or Redis when more than one worker runs.
_calls: dict[str, collections.deque[float]] = {}
_calls_lock = threading.Lock()


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limit: {RATE_LIMIT} queries per {int(RATE_WINDOW)} s; retry in {retry_after} s")


def rate_limit(key: str) -> None:
    now = time.monotonic()
    with _calls_lock:
        q = _calls.setdefault(key, collections.deque())
        while q and now - q[0] >= RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise RateLimited(math.ceil(RATE_WINDOW - (now - q[0])))
        q.append(now)


def audit(u: authen.User, surface: Surface, endpoint: Literal["count", "pivot"], d: Definition,
          patients: int | None) -> None:
    print(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sub": u.sub, "email": u.email,
                      "surface": surface,
                      "endpoint": endpoint, "cohort_id": cohort.cohort_id(d),
                      "definition": d.model_dump(mode="json"), "patients": patients}), flush=True)


# --- shared calls --------------------------------------------------------------------------------

def run_count(u: authen.User, surface: Surface, d: Definition) -> CountResult:
    rate_limit(u.sub)
    r = cohort.count(d)
    audit(u, surface, "count", d, r.patients)
    return r


def run_pivot(u: authen.User, surface: Surface, d: Definition) -> PivotResult:
    rate_limit(u.sub)
    r = cohort.pivot(d)
    audit(u, surface, "pivot", d, r.patients)
    return r


def run_apply(d: Definition, op: Operation) -> ApplyResult:
    new = cohort.apply(d, op, cohort.vocabulary())
    return ApplyResult(definition=new, cohort_id=cohort.cohort_id(new))


def run_options(q: str, limit: int = 20, field: str | None = None, parent: str | None = None) -> Options:
    v = cohort.vocabulary()
    return Options(entries=[Option(field=e.field, parent=e.parent, value=e.value)
                            for e in v.search(q, limit, field, parent)],
                   years=v.years, cut_points=v.cut_points, min_cell=v.min_cell)


def run_schema() -> SchemaInfo:
    return SchemaInfo(version=cohort.SCHEMA_VERSION, definition=cohort.json_schema(),
                      operation=cohort.operation_json_schema(), cut_points=cohort.CUT_POINTS,
                      min_cell=cohort.MIN_CELL)


async def run_save(u: authen.User, d: Definition) -> SavedCohort:
    await run_in_threadpool(lambda: cohort.vocabulary().check(d))
    sid = await run_in_threadpool(cohort.snapshot_id)
    return await saved.create(u.sub, d, snapshot_id=sid)


async def run_saved_apply(u: authen.User, id: uuid.UUID, op: Operation) -> SavedCohort:
    c = await saved.get(u.sub, id)
    new = await run_in_threadpool(lambda: cohort.apply(c.head.definition, op, cohort.vocabulary()))
    sid = await run_in_threadpool(cohort.snapshot_id)
    return await saved.append(u.sub, id, new, op.model_dump(mode="json", by_alias=True), after=c.head.seq,
                              snapshot_id=sid)


async def run_revert(u: authen.User, id: uuid.UUID, to: int) -> SavedCohort:
    return await saved.revert(u.sub, id, to, snapshot_id=await run_in_threadpool(cohort.snapshot_id))


async def run_snapshot(u: authen.User, surface: Surface, id: uuid.UUID) -> Snapshot:
    c = await saved.get(u.sub, id)
    day = cohort.data_date()
    result = await run_in_threadpool(run_count, u, surface, c.head.definition)   # rate-limited + audited
    return await saved.add_snapshot(u.sub, c.head.definition, day, result)


# --- MCP -----------------------------------------------------------------------------------------

TOOL_ERRORS = (DefinitionError, RateLimited, saved.NotFound, saved.Conflict, saved.Unavailable)

mcp_app = MCPServer(name="uccc-genomics-app", title="UCCC genomics cohort tools",
                    description="Floored patient counts over de-identified UCCC Caris + FMI reports",
                    instructions=INSTRUCTIONS)


@mcp_app.tool()
def search_vocabulary(q: str, ctx: Context, limit: int = 20, field: str | None = None,
                      parent: str | None = None) -> Options:
    """Find the vocabulary values (genes, protein changes, oncotree codes, markers, ...) that match
    free text, to put into a cohort definition. Returns values only, no counts. `q` is a
    case-insensitive substring of the value, at most 100 characters; an empty `q` returns nothing
    unless `field` is given (then that field's values). At most 50 results (`limit` is clamped to
    1-50). Each entry's `field` names the definition field the value goes in and `parent` the gene,
    biomarker or IHC marker it belongs under (e.g. `KRAS` for an `alteration.aa` value); pass
    `field` and `parent` back to list one field's values. `field` must be one of
    population.oncotree, population.organ, population.sex, population.age_band, population.vendor,
    population.assay_class, alteration.gene, alteration.aa, biomarker.call, ihc.marker, ihc.clone,
    ihc.call, expression.gene, specimen.site_type, specimen.site, actionability.evidence; any other
    field is an error."""
    _mcp_user(ctx)
    try:
        return run_options(q, limit, field, parent)
    except DefinitionError as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def apply_op(definition: Definition, op: Operation, ctx: Context) -> ApplyResult:
    """Apply one edit operation to a cohort definition and return the new definition and its
    cohort_id. Fails with the offending field or criterion id if the result is invalid."""
    _mcp_user(ctx)
    try:
        return run_apply(definition, op)
    except DefinitionError as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def count(definition: Definition, ctx: Context) -> CountResult:
    """Count distinct patients matching a cohort definition: the funnel, breakdowns, years and, for
    a cohort too small to show, which criterion to loosen (only when loosen_offered is true; when it is
    false no suggestion was computed). null means suppressed (under 5, or hidden so a
    small count cannot be worked out by subtraction), never zero.
    `denominator` is the patients in the population (in a breakdown cell: the population's patients
    with that value), the base for a percentage. `reports` counts the cohort patients' in-population
    reports (Caris and FMI) that match at least one include criterion (an exclude, tested_negative,
    both_vendors or serial criterion never makes a report count), or all of them when no criterion
    can; with scope 'report', the reports on which every criterion holds; it is not a patient count."""
    try:
        return run_count(_mcp_user(ctx), "mcp", definition)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def pivot(definition: Definition, ctx: Context) -> PivotResult:
    """Cross-tabulate a cohort definition's patients by its pivot rows and cols (set `pivot` first,
    with apply_op). null cells are suppressed (under 5, or hidden so a small count cannot be worked out by
    subtraction), never zero."""
    try:
        return run_pivot(_mcp_user(ctx), "mcp", definition)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def describe_definition(ctx: Context) -> SchemaInfo:
    """The JSON Schemas of a cohort definition and of the edit operations, plus the fixed numeric
    cut points and the minimum cell size."""
    _mcp_user(ctx)
    return run_schema()


@mcp_app.tool()
async def save_cohort(definition: Definition, ctx: Context) -> SavedCohort:
    """Save a cohort definition as a new saved cohort of the logged-in user (revision 1)."""
    try:
        return await run_save(_mcp_user(ctx), definition)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def list_saved_cohorts(ctx: Context) -> SavedList:
    """The logged-in user's saved cohorts with their current definition, most recently edited first."""
    try:
        return await saved.list_cohorts(_mcp_user(ctx).sub)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def get_saved_cohort(id: uuid.UUID, ctx: Context) -> SavedCohort:
    """One saved cohort of the logged-in user, with its current (head) revision."""
    try:
        return await saved.get(_mcp_user(ctx).sub, id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def apply_saved_op(id: uuid.UUID, op: Operation, ctx: Context) -> SavedCohort:
    """Apply one edit operation to a saved cohort; the result is a new revision. Fails with the
    offending field or criterion id if the result is invalid."""
    try:
        return await run_saved_apply(_mcp_user(ctx), id, op)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def saved_cohort_history(id: uuid.UUID, ctx: Context) -> History:
    """Every revision of a saved cohort, oldest first, with the operation that made each."""
    try:
        return await saved.history(_mcp_user(ctx).sub, id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def revert_saved_cohort(id: uuid.UUID, to: Annotated[int, Field(ge=1)], ctx: Context) -> SavedCohort:
    """Make a saved cohort's definition equal to revision `to` again, as a new revision (history is kept)."""
    try:
        return await run_revert(_mcp_user(ctx), id, to)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def snapshot_saved_cohort(id: uuid.UUID, ctx: Context) -> Snapshot:
    """Count a saved cohort's current definition and store the suppressed result with the data date,
    for a grant feasibility statement. Counts like `count`: rate-limited and audited."""
    try:
        return await run_snapshot(_mcp_user(ctx), "mcp", id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def delete_saved_cohort(id: uuid.UUID, ctx: Context) -> Deleted:
    """Delete a saved cohort and its revisions. Snapshots already taken are kept."""
    try:
        return await saved.delete(_mcp_user(ctx).sub, id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def list_snapshots(ctx: Context) -> Snapshots:
    """The logged-in user's snapshots, newest first."""
    try:
        return await saved.list_snapshots(_mcp_user(ctx).sub)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def get_cohort_version(cohort_id: str, ctx: Context) -> CohortVersion:
    """Resolve a shared cohort_id to the definition that selects its patients (no name or view
    settings), to save as your own copy. Any logged-in user may resolve any cohort_id."""
    try:
        _mcp_user(ctx)
        return await saved.get_version(cohort_id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def list_my_requests(ctx: Context) -> Requests:
    """The logged-in user's requests for identified data, newest first. Read-only."""
    try:
        return await broker.list_my_requests(_mcp_user(ctx).sub)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def get_my_request(id: uuid.UUID, ctx: Context) -> MyRequestDetail:
    """One of the logged-in user's requests, with its frozen cohort revision, IRB, reviews and releases."""
    try:
        return await broker.get_my_request(_mcp_user(ctx).sub, id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def broker_list_requests(ctx: Context, status: RequestStatus | None = None) -> Requests:
    """Honest broker only: every request, newest first, optionally one status."""
    try:
        _mcp_broker(ctx)
        return await broker.list_requests(status)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def broker_get_request(id: uuid.UUID, ctx: Context) -> RequestDetail:
    """Honest broker only: any request, with its frozen cohort revision, IRB, reviews and releases."""
    try:
        _mcp_broker(ctx)
        return await broker.get_request(id)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def broker_list_irb(ctx: Context) -> IrbList:
    """Honest broker only: the latest version of each IRB authorization in the registry."""
    try:
        _mcp_broker(ctx)
        return await broker.list_irb()
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
async def broker_get_irb(irb_number: Annotated[str, Field(max_length=64)], ctx: Context) -> Irb:
    """Honest broker only: every version of one IRB authorization, with its documents and approved personnel."""
    try:
        _mcp_broker(ctx)
        return await broker.get_irb(irb_number)
    except TOOL_ERRORS as e:
        raise ToolError(str(e)) from None


# --- app -----------------------------------------------------------------------------------------

def app(static_dir: str | None = None) -> FastAPI:
    sub = mcp_app.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    manager = mcp_app.session_manager   # one per streamable_http_app() call, and each runs once

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        url = saved.database_url()
        if url is not None:
            saved.start(url)
        try:
            async with manager.run():
                yield
        finally:
            await saved.stop()

    application = FastAPI(title="UCCC genomics cohort app", lifespan=lifespan, openapi_url="/api/openapi.json",
                          docs_url=None, redoc_url=None)

    @application.exception_handler(DefinitionError)
    def definition_error(request: Request, e: DefinitionError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @application.exception_handler(RateLimited)
    def rate_limited(request: Request, e: RateLimited):
        return JSONResponse({"detail": str(e)}, status_code=429, headers={"Retry-After": str(e.retry_after)})

    @application.exception_handler(saved.NotFound)
    def saved_not_found(request: Request, e: saved.NotFound):
        return JSONResponse({"detail": str(e)}, status_code=404)

    @application.exception_handler(saved.Conflict)
    def saved_conflict(request: Request, e: saved.Conflict):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @application.exception_handler(saved.Unavailable)
    def saved_unavailable(request: Request, e: saved.Unavailable):
        return JSONResponse({"detail": str(e)}, status_code=503)

    @application.get("/api/me")
    def get_me(u: authen.User = Depends(user)) -> Me:
        return Me(sub=u.sub, email=u.email, sign_out=authen.AUTH["mode"] == "authentik")

    @application.post(terms.ACCEPT_PATH, include_in_schema=False)
    async def post_terms_accept(body: TermsAccept, u: authen.User = Depends(user)) -> TermsAccept:
        if body.version != terms.TERMS_VERSION:
            raise HTTPException(409, "the portal terms have changed; reload the page to read the current version")
        await terms.accept(u.sub)
        return TermsAccept(version=terms.TERMS_VERSION)

    @application.post("/api/cohort")
    def post_cohort(d: Definition, u: authen.User = Depends(user)) -> CountResult:
        return run_count(u, "rest", d)

    @application.post("/api/pivot")
    def post_pivot(d: Definition, u: authen.User = Depends(user)) -> PivotResult:
        return run_pivot(u, "rest", d)

    @application.post("/api/apply")
    def post_apply(body: ApplyRequest, u: authen.User = Depends(user)) -> ApplyResult:
        return run_apply(body.definition, body.op)

    @application.get("/api/options")
    def get_options(q: str = "", limit: int = 20,
                    field: Annotated[str | None, Query(description=FIELD_HELP)] = None,
                    parent: Annotated[str | None, Query(description=(
                        "With field: only values under this parent (alteration.aa: gene; "
                        "biomarker.call: TMB/MSI/LOH; ihc.clone, ihc.call: marker)"))] = None,
                    u: authen.User = Depends(user)) -> Options:
        return run_options(q, limit, field, parent)

    @application.get("/api/schema")
    def get_schema(u: authen.User = Depends(user)) -> SchemaInfo:
        return run_schema()

    @application.post("/api/saved")
    async def post_saved(d: Definition, u: authen.User = Depends(user)) -> SavedCohort:
        return await run_save(u, d)

    @application.get("/api/saved")
    async def get_saved_list(u: authen.User = Depends(user)) -> SavedList:
        return await saved.list_cohorts(u.sub)

    @application.get("/api/saved/{id}")
    async def get_saved(id: uuid.UUID, u: authen.User = Depends(user)) -> SavedCohort:
        return await saved.get(u.sub, id)

    @application.post("/api/saved/{id}/apply")
    async def post_saved_apply(id: uuid.UUID, body: SavedApplyRequest, u: authen.User = Depends(user)) -> SavedCohort:
        return await run_saved_apply(u, id, body.op)

    @application.get("/api/saved/{id}/history")
    async def get_saved_history(id: uuid.UUID, u: authen.User = Depends(user)) -> History:
        return await saved.history(u.sub, id)

    @application.post("/api/saved/{id}/revert")
    async def post_saved_revert(id: uuid.UUID, body: RevertRequest, u: authen.User = Depends(user)) -> SavedCohort:
        return await run_revert(u, id, body.to)

    @application.post("/api/saved/{id}/snapshot")
    async def post_saved_snapshot(id: uuid.UUID, u: authen.User = Depends(user)) -> Snapshot:
        return await run_snapshot(u, "rest", id)

    @application.delete("/api/saved/{id}")
    async def delete_saved(id: uuid.UUID, u: authen.User = Depends(user)) -> Deleted:
        return await saved.delete(u.sub, id)

    @application.get("/api/snapshots")
    async def get_snapshots(u: authen.User = Depends(user)) -> Snapshots:
        return await saved.list_snapshots(u.sub)

    @application.get("/api/versions/{cohort_id}")
    async def get_version(cohort_id: str, u: authen.User = Depends(user)) -> CohortVersion:
        return await saved.get_version(cohort_id)

    @application.get("/api/requests")
    async def get_requests(u: authen.User = Depends(user)) -> Requests:
        return await broker.list_my_requests(u.sub)

    @application.get("/api/requests/{id}")
    async def get_request(id: uuid.UUID, u: authen.User = Depends(user)) -> MyRequestDetail:
        return await broker.get_my_request(u.sub, id)

    @application.get("/api/broker/requests")
    async def get_broker_requests(status: RequestStatus | None = None,
                                  u: authen.User = Depends(broker_user)) -> Requests:
        return await broker.list_requests(status)

    @application.get("/api/broker/requests/{id}")
    async def get_broker_request(id: uuid.UUID, u: authen.User = Depends(broker_user)) -> RequestDetail:
        return await broker.get_request(id)

    @application.get("/api/broker/irb")
    async def get_broker_irb_list(u: authen.User = Depends(broker_user)) -> IrbList:
        return await broker.list_irb()

    @application.get("/api/broker/irb/{irb_number}")
    async def get_broker_irb(irb_number: Annotated[str, Path(max_length=64)],
                             u: authen.User = Depends(broker_user)) -> Irb:
        return await broker.get_irb(irb_number)

    @application.get("/api/health")
    def health():
        """Open: 200 only if the de-id file opens and answers. No counts or error text in the body."""
        try:
            con = get_db()
            try:
                con.execute("SELECT count(*) FROM mart.report").fetchone()
            finally:
                con.close()
        except Exception as e:
            print(f"health: {e}", file=sys.stderr, flush=True)
            return JSONResponse({"status": "unhealthy"}, status_code=503)
        return {"status": "Healthy"}

    @application.get("/api/public/summary")
    def get_public_summary(response: Response) -> public.PublicSummary:
        """Open: fixed coarse totals for the landing page. No parameters; every count is floored at 5
        and rounded to the nearest 10 (public.coarse)."""
        try:
            s = public.summary()
        except Exception as e:
            print(f"public summary: {e}", file=sys.stderr, flush=True)
            return JSONResponse({"detail": "totals unavailable"}, status_code=503)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return s

    @application.get("/mcp", include_in_schema=False)
    def get_mcp():
        """No standalone SSE stream (stateless JSON): the MCP spec's answer is 405."""
        return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "POST"})

    application.router.routes.extend(sub.routes)   # exactly /mcp; mounting would 307 to /mcp/
    if authen.AUTH["mode"] == "authentik":
        application.add_api_route("/auth/login", authen.login, methods=["GET"], include_in_schema=False,
                                  response_model=None)
        application.add_api_route("/auth/callback", authen.callback, methods=["GET"], include_in_schema=False,
                                  response_model=None)
        application.add_api_route("/auth/logout", authen.logout, methods=["POST"], include_in_schema=False,
                                  response_model=None)
    if static_dir:   # last, so lowest precedence
        discover = os.path.join(static_dir, "discover.html")
        if os.path.isfile(discover):   # not a discover/ directory: StaticFiles would redirect to an absolute http:// URL
            application.add_api_route("/discover", lambda: FileResponse(discover), methods=["GET"],
                                      include_in_schema=False, response_model=None)
        application.mount("/", StaticFiles(directory=static_dir, html=True))
    application.add_middleware(RequireUser)
    return application


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="UCCC genomics cohort app: REST /api/* and MCP /mcp")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--auth", choices=authen.MODES, required=True,
                    help="access: Cloudflare Access JWT; password: one local account; none: local dev only; "
                         "authentik: campus sign-in through Authentik (AUTHENTIK_*, APP_BASE_URL, SESSION_SECRET in .env)")
    ap.add_argument("--static", help="also serve this built front-end directory (landing page at /, Discover at /discover)")
    args = ap.parse_args(argv)
    authen.configure(args.auth)
    if args.auth in ("access", "authentik") and saved.database_url() is None:
        raise SystemExit(f"--auth {args.auth} needs DATABASE_URL (in .env): portal terms acceptance is "
                         "recorded in Postgres")
    uvicorn.run(app(args.static), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
