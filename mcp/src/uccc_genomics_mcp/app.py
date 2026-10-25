"""genomics-app: REST (/api/*) and MCP (/mcp) over the cohort module, behind authen (docs/specs/35-*.md).

One process, two surfaces, one set of shared calls (`run_*`): the routes and tools add only
transport and error mapping. Every number comes out of `cohort.count` / `cohort.pivot`, already
suppressed; nothing here post-processes counts. `RequireUser` authenticates every request but
GET /api/health, once, outside FastAPI and the MCP SDK.
"""
import argparse
import collections
import json
import math
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

import uccc_genomics.config  # noqa: F401  loads the repo .env (APP_USER, APP_PASSWORD_HASH, ACCESS_*)
from uccc_genomics_mcp import authen, cohort
from uccc_genomics_mcp.cohort import CountResult, Definition, DefinitionError, Operation, PivotResult
from uccc_genomics_mcp.server import get_db

Surface = Literal["rest", "mcp"]

INSTRUCTIONS = (
    "Build a cohort definition (its JSON Schema comes from describe_definition), edit it with apply_op, "
    "map the user's words to vocabulary values with search_vocabulary, then count it, or pivot it once its "
    "pivot is set. Counts are distinct patients. null means suppressed (1-4, or recoverable by subtraction), "
    "never zero. Quote only numbers a tool returned. Never claim the data holds stage, treatment, outcomes, "
    "race or ethnicity.")


# --- auth ----------------------------------------------------------------------------------------

class RequireUser:
    """Pure ASGI middleware around the whole app: every HTTP request except GET /api/health is
    authenticated once with authen.user(); the email goes into the request's scope state."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or (scope["type"] == "http" and scope["path"] == "/api/health"):
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":   # no websocket routes
            return
        try:   # scrypt and the JWKS fetch block
            email = await run_in_threadpool(authen.user, Request(scope))
        except PermissionError as e:
            await JSONResponse({"detail": str(e)}, status_code=401, headers=authen.challenge())(scope, receive, send)
            return
        scope["state"] = {**scope.get("state", {}), "user": email}   # a fresh dict per request
        await self.app(scope, receive, send)


def user(request: Request) -> str:
    """FastAPI dependency: the email RequireUser stored; HTTPException(401) if it is missing."""
    email = getattr(request.state, "user", None)
    if email is None:
        raise HTTPException(401, "not authenticated", headers=authen.challenge())
    return email


def _mcp_user(ctx: Context) -> str:
    """The email RequireUser stored for this MCP POST; ToolError if there is no HTTP request or
    no user (an in-process call that bypassed the middleware)."""
    try:
        return ctx.request_context.request.state.user
    except (ValueError, AttributeError):
        raise ToolError("not authenticated") from None


# --- models --------------------------------------------------------------------------------------

class ApplyRequest(BaseModel):
    definition: Definition
    op: Operation


class ApplyResult(BaseModel):
    definition: Definition
    cohort_id: str


class Option(BaseModel):
    field: str            # VocabEntry.field, e.g. "alteration.gene"
    parent: str | None
    value: str


class Options(BaseModel):
    entries: list[Option]
    years: tuple[int, int] | None
    cut_points: dict[str, list[float]]
    min_cell: int


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
# worker. Move to Postgres or Redis with the saved-cohorts work.
_calls: dict[str, collections.deque[float]] = {}
_calls_lock = threading.Lock()


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limit: {RATE_LIMIT} queries per {int(RATE_WINDOW)} s; retry in {retry_after} s")


def rate_limit(email: str) -> None:
    now = time.monotonic()
    with _calls_lock:
        q = _calls.setdefault(email, collections.deque())
        while q and now - q[0] >= RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise RateLimited(math.ceil(RATE_WINDOW - (now - q[0])))
        q.append(now)


def audit(email: str, surface: Surface, endpoint: Literal["count", "pivot"], d: Definition,
          patients: int | None) -> None:
    print(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "email": email, "surface": surface,
                      "endpoint": endpoint, "cohort_id": cohort.cohort_id(d),
                      "definition": d.model_dump(mode="json"), "patients": patients}), flush=True)


# --- shared calls --------------------------------------------------------------------------------

def run_count(email: str, surface: Surface, d: Definition) -> CountResult:
    rate_limit(email)
    r = cohort.count(d)
    audit(email, surface, "count", d, r.patients)
    return r


def run_pivot(email: str, surface: Surface, d: Definition) -> PivotResult:
    rate_limit(email)
    r = cohort.pivot(d)
    audit(email, surface, "pivot", d, r.patients)
    return r


def run_apply(d: Definition, op: Operation) -> ApplyResult:
    new = cohort.apply(d, op, cohort.vocabulary())
    return ApplyResult(definition=new, cohort_id=cohort.cohort_id(new))


def run_options(q: str, limit: int = 20) -> Options:
    v = cohort.vocabulary()
    return Options(entries=[Option(field=e.field, parent=e.parent, value=e.value) for e in v.search(q, limit)],
                   years=v.years, cut_points=v.cut_points, min_cell=v.min_cell)


def run_schema() -> SchemaInfo:
    return SchemaInfo(version=cohort.SCHEMA_VERSION, definition=cohort.json_schema(),
                      operation=cohort.operation_json_schema(), cut_points=cohort.CUT_POINTS,
                      min_cell=cohort.MIN_CELL)


# --- MCP -----------------------------------------------------------------------------------------

mcp_app = MCPServer(name="uccc-genomics-app", title="UCCC genomics cohort tools",
                    description="Floored patient counts over de-identified UCCC Caris + FMI reports",
                    instructions=INSTRUCTIONS)


@mcp_app.tool()
def search_vocabulary(q: str, ctx: Context, limit: int = 20) -> Options:
    """Find the vocabulary values (genes, protein changes, oncotree codes, markers, ...) that match
    free text, to put into a cohort definition. Returns values only, no counts."""
    _mcp_user(ctx)
    return run_options(q, limit)


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
    a cohort too small to show, which criterion to loosen. null means suppressed, never zero."""
    try:
        return run_count(_mcp_user(ctx), "mcp", definition)
    except (DefinitionError, RateLimited) as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def pivot(definition: Definition, ctx: Context) -> PivotResult:
    """Cross-tabulate a cohort definition's patients by its pivot rows and cols (set `pivot` first,
    with apply_op). null cells are suppressed, never zero."""
    try:
        return run_pivot(_mcp_user(ctx), "mcp", definition)
    except (DefinitionError, RateLimited) as e:
        raise ToolError(str(e)) from None


@mcp_app.tool()
def describe_definition(ctx: Context) -> SchemaInfo:
    """The JSON Schemas of a cohort definition and of the edit operations, plus the fixed numeric
    cut points and the minimum cell size."""
    _mcp_user(ctx)
    return run_schema()


# --- app -----------------------------------------------------------------------------------------

def app(static_dir: str | None = None) -> FastAPI:
    sub = mcp_app.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    manager = mcp_app.session_manager   # one per streamable_http_app() call, and each runs once

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with manager.run():
            yield

    application = FastAPI(title="UCCC genomics cohort app", lifespan=lifespan, openapi_url="/api/openapi.json",
                          docs_url="/api/docs", redoc_url=None)

    @application.exception_handler(DefinitionError)
    def definition_error(request: Request, e: DefinitionError):
        return JSONResponse({"detail": str(e)}, status_code=400)

    @application.exception_handler(RateLimited)
    def rate_limited(request: Request, e: RateLimited):
        return JSONResponse({"detail": str(e)}, status_code=429, headers={"Retry-After": str(e.retry_after)})

    @application.post("/api/cohort")
    def post_cohort(d: Definition, email: str = Depends(user)) -> CountResult:
        return run_count(email, "rest", d)

    @application.post("/api/pivot")
    def post_pivot(d: Definition, email: str = Depends(user)) -> PivotResult:
        return run_pivot(email, "rest", d)

    @application.post("/api/apply")
    def post_apply(body: ApplyRequest, email: str = Depends(user)) -> ApplyResult:
        return run_apply(body.definition, body.op)

    @application.get("/api/options")
    def get_options(q: str = "", limit: int = 20, email: str = Depends(user)) -> Options:
        return run_options(q, limit)

    @application.get("/api/schema")
    def get_schema(email: str = Depends(user)) -> SchemaInfo:
        return run_schema()

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

    application.router.routes.extend(sub.routes)   # exactly /mcp; mounting would 307 to /mcp/
    if static_dir:   # last, so lowest precedence
        application.mount("/", StaticFiles(directory=static_dir, html=True))
    application.add_middleware(RequireUser)
    return application


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="UCCC genomics cohort app: REST /api/* and MCP /mcp")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--auth", choices=authen.MODES, required=True,
                    help="access: Cloudflare Access JWT; password: one local account; none: local dev only")
    ap.add_argument("--static", help="also serve this built front-end directory at / (local dev only)")
    args = ap.parse_args(argv)
    authen.configure(args.auth)
    uvicorn.run(app(args.static), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
