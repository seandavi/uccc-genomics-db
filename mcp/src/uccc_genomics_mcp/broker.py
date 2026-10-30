"""Honest-broker records in Postgres: IRB registry, requests, reviews, releases (docs/specs/132-*.md,
design in docs/HONEST_BROKER.md). The requester writes the intake here (docs/specs/133-*.md): an IRB
version and its document references, a draft request, its requester attestation and submission. Reviews and
releases (#134, #135) and the IRB personnel list are not written here; the broker reads them.

The tables sit on `saved.metadata`, so their foreign keys to `cohort_revision` resolve and Alembic sees them.
Identified data never enters Postgres: `release_patient` holds `research_id` (the keyed hash `deid` makes)
only, and no function here returns it. A request's requester sees their own rows; the broker group sees all
(the caller checks `authen.User.broker`). Someone else's request is indistinguishable from a missing one.
"""
import datetime
import re
import uuid
from typing import Annotated, Literal

import sqlalchemy as sa
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator
from sqlalchemy.dialects.postgresql import JSONB, distinct_on

from uccc_genomics.deid import ID_PATTERN
from uccc_genomics_mcp import saved
from uccc_genomics_mcp.cohort import Definition
from uccc_genomics_mcp.saved import Conflict, Deleted, NotFound, cohort_revision, metadata

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
    sa.Column("title", sa.Text, nullable=True),            # "title or version" the requester gave
    sa.Column("file_ref", sa.Text, nullable=False),        # a link or location the requester gave; no file passes through the app
    sa.Column("sha256", sa.Text, nullable=True),
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

# each signature of the requester attestation; append-only
request_attestation = sa.Table(
    "request_attestation", metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("request_id", sa.Uuid, sa.ForeignKey("request.id"), nullable=False, index=True),
    sa.Column("attestation_version", sa.Text, nullable=False),
    sa.Column("text", sa.Text, nullable=False),            # exactly what was signed
    sa.Column("signed_by", sa.Text, nullable=False),       # sub
    sa.Column("signed_as", sa.Text, nullable=False),       # email, the display label at signing
    _at("signed_at"))

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


IRB_NUMBER = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
IrbNumber = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=IRB_NUMBER)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
DocType = Literal["approval_letter", "personnel_list", "protocol_excerpt", "consent_form"]
RequestField = Literal["demographics", "diagnosis", "specimen", "test", "variants", "copy_number", "fusions",
                       "biomarkers", "ihc", "expression", "genes_tested"]
Identifier = Literal["mrn", "name", "dob", "true_dates", "vendor_report_id"]
EDITABLE = ("draft", "returned")
MAX_DRAFTS = 20          # drafts per requester
MAX_IRB_VERSIONS = 50    # IRB versions registered per user
MAX_DOCUMENTS = 20       # document references per IRB version
LONG_NUMBER = re.compile(r"\d{7,}")

ATTESTATION_VERSION = "2026-10-30"
ATTESTATION_TEXT = (
    "I attest that I and all named recipients are listed on the IRB approval for protocol {irb_number}, that "
    "the approval is active, and that the data requested is the minimum necessary for the purpose described, "
    "which is approved in section {section} of protocol version {protocol_version}. I will use the data only "
    "for that purpose. I will not share it beyond the named recipients, re-disclose it, or link it to other "
    "data except as the protocol permits. I will store it only in {storage_location}, and I will destroy it "
    "or transfer it to the approved study system by {retention_end}. I will notify the honest broker within "
    "24 hours of any suspected unauthorized access or disclosure.")


def _no_identifiers(s: str) -> str:
    """Free text can't carry a run of 7+ digits (an MRN's shape) or a vendor report id (deid.ID_PATTERN,
    ignoring case): patients are described by the cohort, never by identifiers."""
    if LONG_NUMBER.search(s) or re.search(ID_PATTERN, s, re.IGNORECASE):
        raise ValueError("free text can't contain a run of 7 or more digits or a vendor report id; describe "
                         "patients with the cohort, not with identifiers")
    return s


def free_text(min_length: int, max_length: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length),
                     AfterValidator(_no_identifiers)]


class Invalid(Exception): ...       # -> 400 (the request is well formed but can't be saved or submitted as it is)


class Recipient(BaseModel):
    name: free_text(1, 200)
    email: Email


class IdentifierReason(BaseModel):
    identifier: Identifier
    reason: free_text(1, 1000)


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
    doc_type: DocType
    title: str | None = None
    file_ref: str
    sha256: str | None = None
    section_cited: str | None = None
    protocol_version: str | None = None
    created_at: datetime.datetime


class IrbStatus(BaseModel):         # what any requester may see of an IRB version
    irb_number: str
    version: int
    status: Literal["active", "suspended", "closed"]
    expiration_date: datetime.date | None = None
    doc_types: list[DocType]        # the document types referenced for this version: unique, sorted
    registered_by_you: bool         # irb_authorization.created_by == the caller; only they add references


class IrbLookup(BaseModel):
    authorizations: list[IrbStatus]     # latest version per irb_number, irb_number ascending


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


class Attestation(BaseModel):
    attestation_version: str
    text: str
    signed_as: str
    signed_at: datetime.datetime


class MyRequestDetail(Request):         # what a requester sees: the IRB's status, never its people or documents
    irb: IrbStatus | None = None        # the version the request names
    attestation: str | None = None      # the text to sign now: set when status is draft/returned and `missing` is []
    missing: list[str]                  # what blocks submission now; [] when ready, and [] when not editable
    attestations: list[Attestation]     # signed_at ascending
    reviews: list[Review]               # decided_at ascending
    releases: list[Release]             # released_at ascending


class RequestDetail(MyRequestDetail):   # broker only
    irb: IrbVersion | None = None       # the version the request names, with documents and personnel


class Requests(BaseModel):
    requests: list[Request]             # created_at descending, then id


# --- input models --------------------------------------------------------------------------------

class RequestCreate(BaseModel):
    cohort: uuid.UUID
    seq: int = Field(ge=1)


class RequestDraft(BaseModel):          # PUT replaces every editable column
    irb_number: IrbNumber | None = None
    irb_version: int | None = Field(default=None, ge=1)
    purpose: free_text(0, 4000) = ""
    fields: list[RequestField] = Field(default=[], max_length=11)
    identifiers: list[IdentifierReason] = Field(default=[], max_length=5)
    recipients: list[Recipient] = Field(default=[], max_length=20)
    storage_location: free_text(0, 500) = ""
    retention_end: datetime.date | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if (self.irb_number is None) != (self.irb_version is None):
            raise ValueError("irb_number and irb_version are set together")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("fields must be unique")
        if len({i.identifier for i in self.identifiers}) != len(self.identifiers):
            raise ValueError("identifiers must be unique")
        if len({r.email for r in self.recipients}) != len(self.recipients):
            raise ValueError("recipients must have unique emails")
        return self


class IrbCreate(BaseModel):             # registers the next version of irb_number
    irb_number: IrbNumber
    pi: free_text(1, 200)
    approval_date: datetime.date
    expiration_date: datetime.date | None = None
    hipaa_pathway: free_text(1, 200)    # free text, as in #132: the accepted set is a privacy-office question
    approved_population: free_text(1, 2000)

    @model_validator(mode="after")
    def _dates(self):
        if self.expiration_date is not None and self.expiration_date < self.approval_date:
            raise ValueError("expiration_date can't be before approval_date")
        return self


class IrbDocumentCreate(BaseModel):
    doc_type: DocType
    title: free_text(1, 300)            # "title or version", e.g. "Approval letter, amendment 3"
    file_ref: free_text(1, 1000)        # a link or a location; shown as text, never fetched by the app
    section_cited: free_text(1, 200) | None = None
    protocol_version: free_text(1, 100) | None = None

    @model_validator(mode="after")
    def _excerpt(self):
        if self.doc_type == "protocol_excerpt" and not (self.section_cited and self.protocol_version):
            raise ValueError("a protocol excerpt needs section_cited and protocol_version")
        return self


class SubmitRequest(BaseModel):
    attestation: str = Field(max_length=5000)   # the text shown, compared exactly with the server's rendering


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


async def _irb_status(conn, viewer: str, irb_number: str, version: int) -> IrbStatus | None:
    a = (await conn.execute(sa.select(irb_authorization.c.status, irb_authorization.c.expiration_date,
                                      irb_authorization.c.created_by).where(
        irb_authorization.c.irb_number == irb_number, irb_authorization.c.version == version))).first()
    if a is None:
        return None
    types = (await conn.execute(sa.select(irb_document.c.doc_type).where(
        irb_document.c.irb_number == irb_number, irb_document.c.version == version).distinct())).scalars().all()
    return IrbStatus(irb_number=irb_number, version=version, status=a.status, expiration_date=a.expiration_date,
                     doc_types=sorted(types), registered_by_you=a.created_by == viewer)


async def _missing(conn, r: Request) -> list[str]:
    """What blocks submission of r now (the strings of docs/specs/133-*.md § 3), in a fixed order. The IRB
    rules (status, expiry, documents) apply once an IRB is chosen; the rest always do."""
    out = []
    if r.irb_number is None:
        out.append("choose an IRB authorization")
    else:
        n, v = r.irb_number, r.irb_version
        irb = await _irb_status(conn, "", n, v)
        if irb.status != "active":
            out.append(f"IRB {n} version {v} is {irb.status}")
        if irb.expiration_date is not None and irb.expiration_date < datetime.date.today():
            out.append(f"IRB {n} version {v} expired on {irb.expiration_date}")
        for t, label in (("approval_letter", "the IRB approval letter"), ("personnel_list", "the approved personnel list"),
                         ("protocol_excerpt", "the protocol excerpt")):
            if t not in irb.doc_types:
                out.append(f"add a reference to {label}")
    if r.purpose == "":
        out.append("state the purpose")
    if not r.identifiers:
        out.append("choose at least one identifier, with a reason")
    if not r.recipients:
        out.append("name at least one recipient")
    if r.storage_location == "":
        out.append("give the storage location")
    if r.retention_end is None or r.retention_end <= datetime.date.today():
        out.append("give a retention end date after today")
    return out


async def _attestation(conn, r: Request) -> str:
    """The attestation text for r; call only when _missing is empty, so every value is present."""
    excerpt = (await conn.execute(sa.select(irb_document.c.section_cited, irb_document.c.protocol_version).where(
        irb_document.c.irb_number == r.irb_number, irb_document.c.version == r.irb_version,
        irb_document.c.doc_type == "protocol_excerpt")
        .order_by(irb_document.c.created_at.desc(), irb_document.c.id.desc()).limit(1))).one()
    return ATTESTATION_TEXT.format(irb_number=r.irb_number, section=excerpt.section_cited,
                                   protocol_version=excerpt.protocol_version, storage_location=r.storage_location,
                                   retention_end=r.retention_end.isoformat())


async def _detail(conn, where, *, broker: bool, viewer: str = "") -> MyRequestDetail:
    row = (await conn.execute(_requests().where(where))).first()
    if row is None:
        raise NotFound
    r = _request(row)
    attestations = (await conn.execute(sa.select(request_attestation).where(request_attestation.c.request_id == r.id)
                                       .order_by(request_attestation.c.signed_at, request_attestation.c.id))).all()
    reviews = (await conn.execute(sa.select(review).where(review.c.request_id == r.id)
                                  .order_by(review.c.decided_at, review.c.id))).all()
    releases = (await conn.execute(sa.select(release).where(release.c.request_id == r.id)
                                   .order_by(release.c.released_at, release.c.id))).all()
    irb, missing, attestation = None, [], None
    if r.irb_number is not None:
        irb = await (_irb_version(conn, r.irb_number, r.irb_version) if broker
                     else _irb_status(conn, viewer, r.irb_number, r.irb_version))
    if not broker and r.status in EDITABLE:
        missing = await _missing(conn, r)
        if not missing:
            attestation = await _attestation(conn, r)
    return (RequestDetail if broker else MyRequestDetail)(
        **{k: getattr(r, k) for k in Request.model_fields}, irb=irb, attestation=attestation, missing=missing,
        attestations=[Attestation(**{k: getattr(a, k) for k in Attestation.model_fields}) for a in attestations],
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
                                 broker=False, viewer=requester)
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


# --- requester writes ----------------------------------------------------------------------------

async def lookup_irb(requester: str, q: str) -> IrbLookup:
    async with saved._begin() as conn:
        latest = (sa.select(irb_authorization.c.irb_number, irb_authorization.c.version)
                  .where(irb_authorization.c.irb_number.istartswith(q, autoescape=True))
                  .ext(distinct_on(irb_authorization.c.irb_number))
                  .order_by(irb_authorization.c.irb_number, irb_authorization.c.version.desc()).limit(20))
        rows = (await conn.execute(latest)).all()
        return IrbLookup(authorizations=[await _irb_status(conn, requester, r.irb_number, r.version) for r in rows])


async def register_irb(requester: str, a: IrbCreate) -> IrbStatus:
    try:
        async with saved._begin() as conn:
            versions = (await conn.execute(sa.select(irb_authorization.c.version).where(
                irb_authorization.c.irb_number == a.irb_number).with_for_update())).scalars().all()
            mine = await conn.scalar(sa.select(sa.func.count()).select_from(irb_authorization)
                                     .where(irb_authorization.c.created_by == requester))
            if mine >= MAX_IRB_VERSIONS:
                raise Conflict(f"at most {MAX_IRB_VERSIONS} IRB versions per user")
            version = max(versions, default=0) + 1
            await conn.execute(sa.insert(irb_authorization).values(
                **a.model_dump(), version=version, status="active", created_by=requester))
            return await _irb_status(conn, requester, a.irb_number, version)
    except sa.exc.IntegrityError:   # a concurrent registration took the version
        raise Conflict(f"IRB {a.irb_number} changed; try again") from None


async def add_irb_document(requester: str, irb_number: str, version: int, d: IrbDocumentCreate) -> IrbStatus:
    async with saved._begin() as conn:
        creator = await conn.scalar(sa.select(irb_authorization.c.created_by).where(
            irb_authorization.c.irb_number == irb_number, irb_authorization.c.version == version).with_for_update())
        if creator is None:
            raise NotFound(f"no IRB authorization {irb_number} version {version}")
        if creator != requester:
            raise Conflict(f"IRB {irb_number} version {version} was registered by someone else; "
                           "register a new version to add documents")
        n = await conn.scalar(sa.select(sa.func.count()).select_from(irb_document).where(
            irb_document.c.irb_number == irb_number, irb_document.c.version == version))
        if n >= MAX_DOCUMENTS:
            raise Conflict(f"at most {MAX_DOCUMENTS} document references per IRB version")
        await conn.execute(sa.insert(irb_document).values(
            **d.model_dump(), id=uuid.uuid4(), irb_number=irb_number, version=version, sha256=None,
            created_by=requester))
        return await _irb_status(conn, requester, irb_number, version)


async def _lock_request(conn, requester: str, id: uuid.UUID):
    row = (await conn.execute(sa.select(request.c.status).where(request.c.id == id, request.c.requester == requester)
                              .with_for_update())).first()
    if row is None:
        raise NotFound(f"no request {id}")
    return row


def _editable(id: uuid.UUID, status: str) -> None:
    if status not in EDITABLE:
        raise Conflict(f"request {id} is {status}; only a draft or a returned request can be changed")


async def create_request(requester: str, r: RequestCreate) -> MyRequestDetail:
    async with saved._begin() as conn:
        head = await saved._lock_head(conn, requester, r.cohort)   # someone else's cohort is a 404
        if r.seq > head:
            raise NotFound(f"no revision {r.seq}")
        drafts = await conn.scalar(sa.select(sa.func.count()).select_from(request).where(
            request.c.requester == requester, request.c.status == "draft"))
        if drafts >= MAX_DRAFTS:
            raise Conflict(f"at most {MAX_DRAFTS} draft requests per user; submit or delete one")
        id = uuid.uuid4()
        await conn.execute(sa.insert(request).values(
            id=id, requester=requester, cohort=r.cohort, seq=r.seq, purpose="", fields=[], identifiers=[],
            recipients=[], storage_location="", status="draft"))
        return await _detail(conn, request.c.id == id, broker=False, viewer=requester)


async def update_request(requester: str, id: uuid.UUID, r: RequestDraft) -> MyRequestDetail:
    async with saved._begin() as conn:
        status = (await _lock_request(conn, requester, id)).status
        _editable(id, status)
        if r.irb_number is not None and not (await conn.execute(sa.select(sa.literal(1)).where(
                sa.exists().where(irb_authorization.c.irb_number == r.irb_number,
                                  irb_authorization.c.version == r.irb_version)))).first():
            raise Invalid(f"no IRB authorization {r.irb_number} version {r.irb_version}")
        if status != "draft" and (r.irb_number is None or r.retention_end is None):   # the table's CHECK
            raise Invalid(f"a {status} request keeps its IRB authorization and retention end date")
        d = r.model_dump(mode="json")
        await conn.execute(sa.update(request).where(request.c.id == id).values(
            irb_number=r.irb_number, irb_version=r.irb_version, purpose=r.purpose, fields=d["fields"],
            identifiers=d["identifiers"], recipients=d["recipients"], storage_location=r.storage_location,
            retention_end=r.retention_end, updated_at=sa.func.now()))
        return await _detail(conn, request.c.id == id, broker=False, viewer=requester)


async def submit_request(requester: str, signed_as: str, id: uuid.UUID, attestation: str) -> MyRequestDetail:
    async with saved._begin() as conn:
        _editable(id, (await _lock_request(conn, requester, id)).status)
        r = _request((await conn.execute(_requests().where(request.c.id == id))).first())
        missing = await _missing(conn, r)
        if missing:
            raise Invalid("can't submit yet: " + "; ".join(missing))
        if attestation != await _attestation(conn, r):
            raise Conflict("the request or its IRB changed since you read the attestation; read it again")
        await conn.execute(sa.insert(request_attestation).values(
            id=uuid.uuid4(), request_id=id, attestation_version=ATTESTATION_VERSION, text=attestation,
            signed_by=requester, signed_as=signed_as))
        await conn.execute(sa.update(request).where(request.c.id == id).values(
            status="submitted", updated_at=sa.func.now()))
        return await _detail(conn, request.c.id == id, broker=False, viewer=requester)


async def delete_request(requester: str, id: uuid.UUID) -> Deleted:
    async with saved._begin() as conn:
        status = (await _lock_request(conn, requester, id)).status
        if status != "draft":
            raise Conflict(f"request {id} was submitted; it is kept as a record and can't be deleted")
        await conn.execute(sa.delete(request).where(request.c.id == id))
        return Deleted(id=id)
