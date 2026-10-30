"""Honest-broker records in Postgres: IRB registry, requests, reviews, releases (docs/specs/132-*.md,
design in docs/HONEST_BROKER.md). Read-only here: rows come from #133 (requests), #134 (reviews) and
#135 (releases).

The tables sit on `saved.metadata`, so their foreign keys to `cohort_revision` resolve and Alembic sees them.
Identified data never enters Postgres: `release_patient` holds `research_id` (the keyed hash `deid` makes)
only, and no function here returns it. A request's requester sees their own rows; the broker group sees all
(the caller checks `authen.User.broker`). Someone else's request is indistinguishable from a missing one.
"""
import datetime
import uuid
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB, distinct_on

from uccc_genomics_mcp import saved
from uccc_genomics_mcp.cohort import Definition
from uccc_genomics_mcp.saved import NotFound, cohort_revision, metadata

SHA256 = "{} ~ '^[0-9a-f]{{64}}$'"


def _at(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


irb_authorization = sa.Table(
    "irb_authorization", metadata,
    sa.Column("irb_number", sa.Text, primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("pi", sa.Text, nullable=False),
    sa.Column("approval_date", sa.Date, nullable=False),
    sa.Column("expiration_date", sa.Date, nullable=True),   # NULL = no expiration (exempt determinations)
    sa.Column("hipaa_pathway", sa.Text, nullable=False),
    sa.Column("approved_population", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),          # "expired" is derived from expiration_date, never stored
    sa.Column("created_by", sa.Text, nullable=False),
    _at("created_at"),
    sa.CheckConstraint("version >= 1"),
    sa.CheckConstraint("status IN ('active','suspended','closed')"))

irb_document = sa.Table(
    "irb_document", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("irb_number", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("doc_type", sa.Text, nullable=False),
    sa.Column("file_ref", sa.Text, nullable=False),        # SharePoint path; no content is stored
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("section_cited", sa.Text, nullable=True),
    sa.Column("protocol_version", sa.Text, nullable=True),
    sa.Column("created_by", sa.Text, nullable=False),
    _at("created_at"),
    sa.ForeignKeyConstraint(["irb_number", "version"], ["irb_authorization.irb_number",
                                                        "irb_authorization.version"]),
    sa.CheckConstraint("doc_type IN ('approval_letter','personnel_list','protocol_excerpt','consent_form')"),
    sa.CheckConstraint(SHA256.format("sha256")))

# for the broker's checklist only; never used to authorize
irb_personnel = sa.Table(
    "irb_personnel", metadata,
    sa.Column("irb_number", sa.Text, primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("person_id", sa.Text, primary_key=True),     # campus email as on the approved list, lower-cased
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("role", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(["irb_number", "version"], ["irb_authorization.irb_number",
                                                        "irb_authorization.version"]))

request = sa.Table(
    "request", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("requester", sa.Text, nullable=False, index=True),
    sa.Column("cohort", sa.Uuid, nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),          # with cohort: the frozen query version
    sa.Column("irb_number", sa.Text, nullable=True),
    sa.Column("irb_version", sa.Integer, nullable=True),
    sa.Column("purpose", sa.Text, nullable=False),
    sa.Column("fields", JSONB, nullable=False),
    sa.Column("identifiers", JSONB, nullable=False),
    sa.Column("recipients", JSONB, nullable=False),
    sa.Column("storage_location", sa.Text, nullable=False),
    sa.Column("retention_end", sa.Date, nullable=True),
    sa.Column("status", sa.Text, nullable=False),
    _at("created_at"),
    _at("updated_at"),
    sa.ForeignKeyConstraint(["cohort", "seq"], ["cohort_revision.cohort", "cohort_revision.seq"],
                            ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["irb_number", "irb_version"], ["irb_authorization.irb_number",
                                                            "irb_authorization.version"]),
    sa.CheckConstraint("status IN ('draft','submitted','returned','approved','denied','fulfilled','closed')"),
    # only a draft may lack an IRB or a retention date
    sa.CheckConstraint("status = 'draft' OR (irb_number IS NOT NULL AND irb_version IS NOT NULL "
                       "AND retention_end IS NOT NULL)"))

review = sa.Table(
    "review", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("request_id", sa.Uuid, sa.ForeignKey("request.id"), nullable=False, index=True),
    sa.Column("reviewer", sa.Text, nullable=False),
    sa.Column("checklist", JSONB, nullable=False),
    sa.Column("decision", sa.Text, nullable=False),
    sa.Column("notes", sa.Text, nullable=False),
    _at("decided_at"),
    sa.CheckConstraint("decision IN ('approve','return','deny')"))

release = sa.Table(
    "release", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("request_id", sa.Uuid, sa.ForeignKey("request.id"), nullable=False, index=True),
    sa.Column("file_name", sa.Text, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("row_count", sa.Integer, nullable=False),
    sa.Column("fields_released", JSONB, nullable=False),
    sa.Column("recipients", JSONB, nullable=False),
    sa.Column("sharepoint_link", sa.Text, nullable=False),
    _at("released_at"),
    sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("closeout_attested_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(SHA256.format("sha256")),
    sa.CheckConstraint("row_count >= 0"))

# study ids of the patients in a release; the design's `study_id` is `research_id`. Never returned here.
release_patient = sa.Table(
    "release_patient", metadata,
    sa.Column("release_id", sa.Uuid, sa.ForeignKey("release.id"), primary_key=True),
    sa.Column("research_id", sa.Text, primary_key=True, index=True),
    sa.CheckConstraint("research_id ~ '^[0-9a-f]{16}$'"))   # the shape deid makes: an MRN or name can't fit


# --- response models -----------------------------------------------------------------------------

RequestStatus = Literal["draft", "submitted", "returned", "approved", "denied", "fulfilled", "closed"]


class Recipient(BaseModel):
    name: str
    email: str


class IdentifierReason(BaseModel):
    identifier: str
    reason: str


class IrbAuthorization(BaseModel):
    irb_number: str
    version: int
    pi: str
    approval_date: datetime.date
    expiration_date: datetime.date | None = None
    hipaa_pathway: str
    approved_population: str
    status: Literal["active", "suspended", "closed"]
    created_at: datetime.datetime


class IrbDocument(BaseModel):
    id: uuid.UUID
    doc_type: Literal["approval_letter", "personnel_list", "protocol_excerpt", "consent_form"]
    file_ref: str
    sha256: str
    section_cited: str | None = None
    protocol_version: str | None = None
    created_at: datetime.datetime


class IrbPerson(BaseModel):
    person_id: str
    name: str
    role: str


class IrbVersion(IrbAuthorization):
    documents: list[IrbDocument]        # created_at ascending
    personnel: list[IrbPerson]          # person_id ascending


class Irb(BaseModel):
    irb_number: str
    versions: list[IrbVersion]          # version ascending


class IrbList(BaseModel):
    authorizations: list[IrbAuthorization]   # latest version per irb_number, irb_number ascending


class Review(BaseModel):
    id: uuid.UUID
    reviewer: str
    checklist: dict[str, bool]
    decision: Literal["approve", "return", "deny"]
    notes: str
    decided_at: datetime.datetime


class Release(BaseModel):               # no patient list: release_patient is never returned
    id: uuid.UUID
    file_name: str
    sha256: str
    row_count: int
    fields_released: list[str]
    recipients: list[Recipient]
    sharepoint_link: str
    released_at: datetime.datetime
    removed_at: datetime.datetime | None = None
    closeout_attested_at: datetime.datetime | None = None


class Request(BaseModel):
    id: uuid.UUID
    requester: str
    cohort: uuid.UUID
    seq: int
    cohort_id: str
    definition: Definition              # the frozen revision
    snapshot_id: str | None = None
    irb_number: str | None = None
    irb_version: int | None = None
    purpose: str
    fields: list[str]
    identifiers: list[IdentifierReason]
    recipients: list[Recipient]
    storage_location: str
    retention_end: datetime.date | None = None
    status: RequestStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MyRequestDetail(Request):         # what a requester sees: the IRB's status, never its people or documents
    irb: IrbAuthorization | None = None  # the version the request names
    reviews: list[Review]               # decided_at ascending
    releases: list[Release]             # released_at ascending


class RequestDetail(MyRequestDetail):   # broker only
    irb: IrbVersion | None = None       # the version the request names, with documents and personnel


class Requests(BaseModel):
    requests: list[Request]             # created_at descending, then id


# --- reads ---------------------------------------------------------------------------------------

def _request(row) -> Request:
    return Request(
        id=row.id, requester=row.requester, cohort=row.cohort, seq=row.seq, cohort_id=row.cohort_id,
        definition=Definition.model_validate(row.definition), snapshot_id=row.snapshot_id,
        irb_number=row.irb_number, irb_version=row.irb_version, purpose=row.purpose, fields=row.fields,
        identifiers=row.identifiers, recipients=row.recipients, storage_location=row.storage_location,
        retention_end=row.retention_end, status=row.status, created_at=row.created_at, updated_at=row.updated_at)


def _requests():
    """SELECT of requests joined to the cohort revision they froze."""
    return (sa.select(*request.c, cohort_revision.c.cohort_id, cohort_revision.c.definition,
                      cohort_revision.c.snapshot_id)
            .join_from(request, cohort_revision, sa.and_(cohort_revision.c.cohort == request.c.cohort,
                                                         cohort_revision.c.seq == request.c.seq))
            .order_by(request.c.created_at.desc(), request.c.id))


async def _irb_authorization(conn, irb_number: str, version: int) -> IrbAuthorization | None:
    a = (await conn.execute(sa.select(irb_authorization).where(
        irb_authorization.c.irb_number == irb_number, irb_authorization.c.version == version))).first()
    return None if a is None else IrbAuthorization(**{k: getattr(a, k) for k in IrbAuthorization.model_fields})


async def _irb_version(conn, irb_number: str, version: int) -> IrbVersion | None:
    a = await _irb_authorization(conn, irb_number, version)
    if a is None:
        return None
    docs = (await conn.execute(sa.select(irb_document).where(
        irb_document.c.irb_number == irb_number, irb_document.c.version == version)
        .order_by(irb_document.c.created_at, irb_document.c.id))).all()
    people = (await conn.execute(sa.select(irb_personnel).where(
        irb_personnel.c.irb_number == irb_number, irb_personnel.c.version == version)
        .order_by(irb_personnel.c.person_id))).all()
    return IrbVersion(
        **a.model_dump(),
        documents=[IrbDocument(**{k: getattr(d, k) for k in IrbDocument.model_fields}) for d in docs],
        personnel=[IrbPerson(person_id=p.person_id, name=p.name, role=p.role) for p in people])


async def _detail(conn, where, *, broker: bool) -> MyRequestDetail:
    row = (await conn.execute(_requests().where(where))).first()
    if row is None:
        raise NotFound
    r = _request(row)
    reviews = (await conn.execute(sa.select(review).where(review.c.request_id == r.id)
                                  .order_by(review.c.decided_at, review.c.id))).all()
    releases = (await conn.execute(sa.select(release).where(release.c.request_id == r.id)
                                   .order_by(release.c.released_at, release.c.id))).all()
    irb = None
    if r.irb_number is not None:
        irb = await (_irb_version if broker else _irb_authorization)(conn, r.irb_number, r.irb_version)
    return (RequestDetail if broker else MyRequestDetail)(
        **{k: getattr(r, k) for k in Request.model_fields}, irb=irb,
        reviews=[Review(**{k: getattr(v, k) for k in Review.model_fields}) for v in reviews],
        releases=[Release(**{k: getattr(v, k) for k in Release.model_fields}) for v in releases])


async def list_my_requests(requester: str) -> Requests:
    async with saved._begin() as conn:
        rows = (await conn.execute(_requests().where(request.c.requester == requester))).all()
        return Requests(requests=[_request(r) for r in rows])


async def get_my_request(requester: str, id: uuid.UUID) -> MyRequestDetail:
    async with saved._begin() as conn:
        try:
            return await _detail(conn, sa.and_(request.c.id == id, request.c.requester == requester),
                                 broker=False)
        except NotFound:
            raise NotFound(f"no request {id}") from None


async def list_requests(status: RequestStatus | None = None) -> Requests:
    async with saved._begin() as conn:
        q = _requests() if status is None else _requests().where(request.c.status == status)
        return Requests(requests=[_request(r) for r in (await conn.execute(q)).all()])


async def get_request(id: uuid.UUID) -> RequestDetail:
    async with saved._begin() as conn:
        try:
            return await _detail(conn, request.c.id == id, broker=True)
        except NotFound:
            raise NotFound(f"no request {id}") from None


async def list_irb() -> IrbList:
    async with saved._begin() as conn:
        latest = (sa.select(irb_authorization).ext(distinct_on(irb_authorization.c.irb_number))
                  .order_by(irb_authorization.c.irb_number, irb_authorization.c.version.desc()))
        rows = (await conn.execute(latest)).all()
        return IrbList(authorizations=[IrbAuthorization(**{k: getattr(r, k) for k in IrbAuthorization.model_fields})
                                       for r in rows])


async def get_irb(irb_number: str) -> Irb:
    async with saved._begin() as conn:
        versions = (await conn.execute(sa.select(irb_authorization.c.version).where(
            irb_authorization.c.irb_number == irb_number).order_by(irb_authorization.c.version))).scalars().all()
        if not versions:
            raise NotFound(f"no IRB authorization {irb_number}")
        return Irb(irb_number=irb_number, versions=[await _irb_version(conn, irb_number, v) for v in versions])
