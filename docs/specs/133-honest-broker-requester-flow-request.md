# #133 Honest broker: requester flow (request, intake, attestation, My requests)

Design record: `docs/HONEST_BROKER.md` (Sean's decisions at the top). Part of #16. Builds on #132 (the tables
and read endpoints in `mcp/src/uccc_genomics_mcp/broker.py`) and #131 (the terms gate).

Scope (Sean, 2026-10-30, issue comment and the orchestrator's answer for this spec):

- The portal goes as far as **submitting** a request: intake, document references, attestation and
  My requests. It never shows sample rows or anything identified. Review, fulfillment, exports and
  deliveries run outside the app (#134, #136 on hold; #135 closed).
- Requesting is open to any Tier 1 user who has accepted the portal terms. The IRB personnel check, done by
  the broker, is the gate.
- **No file uploads in the app.** The intake records each IRB document as a **reference**: its type, a
  title or version, and a link or location that the requester gives. The broker files copies in SharePoint
  with a host script outside the app. The container mounts and the AGENTS.md deployment rule stay as they
  are. This replaces the issue's "server-side uploader (rclone)" line, and `docs/HONEST_BROKER.md` decision 4
  is updated in this PR.
- The items carried over from #132's reviews are in scope (§6).

Identified data never enters Postgres, logs, the repo or GitHub. The new rows hold staff `sub`s, staff
names and emails, IRB metadata, free text that a guard checks (§2), and references to cohort revisions. They
never hold an MRN, a patient name, a date of birth or a vendor report id.

## Goal

1. In Discover, **Request identified data** saves the current cohort definition as a new saved cohort and
   opens a draft request on revision 1 of that saved cohort, on a new page, `/requests`.
2. On `/requests` the requester fills in the intake:
   - an IRB authorization: look it up by number to see its status, expiry and which documents are
     referenced, or register a new IRB version;
   - document references: approval letter, personnel list, protocol excerpt (section and protocol
     version), and the consent/HIPAA form when relevant;
   - purpose, fields, identifiers each with a reason, recipients, storage location and retention end.
3. The requester signs the design's **requester attestation** (its text filled in from the request) and
   submits. Each signature is stored.
4. **My requests** lists the requester's requests with their status. A request's detail shows its frozen
   cohort, broker messages (review notes), release dates and the retention deadline, all read-only.
5. The #132 review follow-ups are resolved (§6).

## Non-goals

- File uploads, rclone, SharePoint writes or any new container mount (see Scope).
- Closeout attestation, expiry flags and the release ledger (#136, on hold). My requests shows
  `retention_end` and release dates read-only.
- Any broker write: reviews, `irb_personnel` rows, IRB status changes, releases (#134 and #135 are on hold
  or closed). Personnel rows are not entered by the requester. The broker transcribes them from the
  referenced personnel list outside the app, if at all.
- Write tools over MCP. Attestation is a person's act in the browser, so the MCP surface stays read-only for
  requests (`list_my_requests`, `get_my_request` and the `broker_*` tools are unchanged).
- Changing the cohort of an existing request. A requester who needs a different cohort deletes the draft
  (or, for a returned request, starts a new one).
- Withdrawing a submitted request, and broker notifications (the broker polls
  `broker_list_requests(status="submitted")`).
- Grant id and trial id (#16 comment): not in the design's data model and not asked for here.
- Any change to the pipeline, `deid`, the de-id file or `research_id`/`report_id`.

## Design

### 1. Schema: migration `0004` (`mcp/src/uccc_genomics_mcp/migrations/versions/0004_request_intake.py`)

`revision = "0004"`, `down_revision = "0003"`. Same style as `0002`.

`upgrade()`:

- `op.alter_column("irb_document", "sha256", existing_type=sa.Text(), nullable=True)`. No file passes
  through the app, so there is nothing to hash. The existing `CHECK (sha256 ~ '^[0-9a-f]{64}$')` stays and
  passes NULL.
- `op.add_column("irb_document", sa.Column("title", sa.Text(), nullable=True))`. Every row this issue
  writes has a title. The column is nullable so the migration cannot fail on rows from before #133.
- `op.create_table("request_attestation", ...)`, with `op.create_index("ix_request_attestation_request_id", ...)`:

| column | type | null | notes |
|---|---|---|---|
| id | Uuid | no | PK |
| request_id | Uuid | no | FK → `request.id` (default NO ACTION: audit rows are never cascaded away) |
| attestation_version | Text | no | `ATTESTATION_VERSION` at signing |
| text | Text | no | the exact text the requester signed |
| signed_by | Text | no | `sub` |
| signed_as | Text | no | `authen.User.email` (the display label) at signing |
| signed_at | timestamptz | no | default now() |

`downgrade()` drops the index and `request_attestation`, then drops `irb_document.title`. It runs
`DELETE FROM irb_document WHERE sha256 IS NULL` (the references #133 wrote), then sets `sha256` back to
NOT NULL. **The downgrade deletes document references.** That is stated in the docstring.

`broker.py` metadata matches: `irb_document` gets `sa.Column("title", sa.Text, nullable=True)` and
`sha256` becomes `nullable=True`. The `file_ref` comment becomes "a link or location the requester gave; no
file passes through the app". `request_attestation` is a new `sa.Table` on `saved.metadata` with
`request_id` `sa.ForeignKey("request.id")`, `index=True`, and `_at("signed_at")`. `command.check` in
`tests/test_saved.py::pg_url` keeps the two in agreement.

### 2. Input models and constants (`broker.py`)

```python
IRB_NUMBER = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
IrbNumber = Annotated[str, StringConstraints(strip_whitespace=True, pattern=IRB_NUMBER)]
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
```

`ID_PATTERN` is imported from `uccc_genomics.deid`, so there is one definition. `deid` imports only
`config` and the stdlib. Every string a requester types goes through `free_text`. The exceptions are the
emails (`Email`) and the IRB number (`IrbNumber`), which have their own patterns. A refusal is a pydantic
`ValueError`, so FastAPI answers 422. `StringConstraints` and `AfterValidator` are pydantic 2.13 (installed).
`IrbNumber` also upper-cases (`to_upper`), so `test-1` and `TEST-1` are one number and the next version of it
(the lookup is case-insensitive, so the number must not be case-sensitive anywhere else). Checked:
`strip_whitespace` runs before `pattern`, and `../x` fails `IRB_NUMBER`.

The #132 response models become stricter in place, so each concept keeps one model:

```python
class Recipient(BaseModel):        name: free_text(1, 200); email: Email
class IdentifierReason(BaseModel): identifier: Identifier; reason: free_text(1, 1000)
```

`Request.fields` stays `list[str]` in the response. Only the input is restricted to `RequestField`.

New input models:

```python
class RequestCreate(BaseModel):
    cohort: uuid.UUID
    seq: int = Field(ge=1)

class RequestDraft(BaseModel):     # PUT replaces every editable column
    irb_number: IrbNumber | None = None
    irb_version: int | None = Field(default=None, ge=1)
    purpose: free_text(0, 4000) = ""
    fields: list[RequestField] = Field(default=[], max_length=11)
    identifiers: list[IdentifierReason] = Field(default=[], max_length=5)
    recipients: list[Recipient] = Field(default=[], max_length=20)
    storage_location: free_text(0, 500) = ""
    retention_end: datetime.date | None = None
    # model_validator(mode="after"): irb_number and irb_version both set or both None; fields unique;
    # identifiers unique by identifier; recipients unique by email. ValueError otherwise (422).

class IrbCreate(BaseModel):        # registers the next version of irb_number
    irb_number: IrbNumber
    pi: free_text(1, 200)
    approval_date: datetime.date
    expiration_date: datetime.date | None = None
    hipaa_pathway: free_text(1, 200)        # free text, as in #132: the accepted set is a privacy-office question
    approved_population: free_text(1, 2000)
    # model_validator: expiration_date, when set, is on or after approval_date

class IrbDocumentCreate(BaseModel):
    doc_type: DocType
    title: free_text(1, 300)                # "title or version", e.g. "Approval letter, amendment 3"
    file_ref: free_text(1, 1000)            # a link or a location; shown as text, never fetched by the app
    section_cited: free_text(1, 200) | None = None
    protocol_version: free_text(1, 100) | None = None
    # model_validator: doc_type == "protocol_excerpt" requires section_cited and protocol_version

class SubmitRequest(BaseModel):
    attestation: str = Field(max_length=5000)   # the text shown, compared exactly with the server's rendering
```

### 3. Response models (`broker.py`)

```python
class IrbStatus(BaseModel):        # what any requester may see of an IRB version
    irb_number: str
    version: int
    status: Literal["active", "suspended", "closed"]
    expiration_date: datetime.date | None = None
    doc_types: list[DocType]       # the document types referenced for this version: unique, sorted
    registered_by_you: bool        # irb_authorization.created_by == the caller; only they add references

class IrbLookup(BaseModel):        authorizations: list[IrbStatus]   # latest version per irb_number, irb_number ascending

class Attestation(BaseModel):
    attestation_version: str; text: str; signed_as: str; signed_at: datetime.datetime

class MyRequestDetail(Request):
    irb: IrbStatus | None = None   # CHANGED from IrbAuthorization: status, expiry and document types only (code-r1-2)
    attestation: str | None = None  # the text to sign now: set when status is draft/returned and `missing` is []
    missing: list[str]             # what blocks submission now; [] when ready, and [] when not editable
    attestations: list[Attestation]  # signed_at ascending
    reviews: list[Review]
    releases: list[Release]

class RequestDetail(MyRequestDetail):   # broker, unchanged apart from the inherited fields
    irb: IrbVersion | None = None
```

`IrbDocument` (the broker view) gains `title: str | None = None`, and its `sha256` becomes
`str | None = None`. The requester never sees `IrbDocument` or `IrbVersion`, so `file_ref`, `pi`,
personnel and dates other than expiry are not in requester responses.

`missing` holds fixed strings, in this order. `n` and `v` are the IRB number and version, and `today` is
`datetime.date.today()` (the container's TZ is America/Denver):

1. `"choose an IRB authorization"` if `irb_number` is NULL. When that is true, rules 2-4 (the ones about the IRB) are skipped; the others still apply.
2. `f"IRB {n} version {v} is {status}"` if the status isn't `active`.
3. `f"IRB {n} version {v} expired on {expiration_date}"` if `expiration_date < today`.
4. `"add a reference to the IRB approval letter"`, `"... to the approved personnel list"` and `"... to the
   protocol excerpt"`, one string for each of the three types the version lacks. `consent_form` is
   optional ("when relevant").
5. `"state the purpose"` if `purpose == ""`.
6. `"choose at least one identifier, with a reason"` if `identifiers == []`.
7. `"name at least one recipient"` if `recipients == []`.
8. `"give the storage location"` if `storage_location == ""`.
9. `"give a retention end date after today"` if `retention_end` is NULL or `<= today`.

Fields are optional. A request may ask only for identifiers, for example a contact list for recruitment.

**Attestation text** (module constants, the design's § "Requester attestation" verbatim apart from the
placeholders):

```python
ATTESTATION_VERSION = "2026-10-30"
ATTESTATION_TEXT = (
    "I attest that I and all named recipients are listed on the IRB approval for protocol {irb_number}, that "
    "the approval is active, and that the data requested is the minimum necessary for the purpose described, "
    "which is approved in section {section} of protocol version {protocol_version}. I will use the data only "
    "for that purpose. I will not share it beyond the named recipients, re-disclose it, or link it to other "
    "data except as the protocol permits. I will store it only in {storage_location}, and I will destroy it "
    "or transfer it to the approved study system by {retention_end}. I will notify the honest broker within "
    "24 hours of any suspected unauthorized access or disclosure.")
```

`async def _attestation(conn, r: Request) -> str` fills it in. `section` and `protocol_version` come from
the newest `protocol_excerpt` reference of the request's IRB version (`created_at DESC, id DESC`), and
`retention_end` is ISO (`2027-06-01`). It is called only when `missing == []`, so every value is present.
To change the wording, edit the text and bump the version, as with `terms.py`.

### 4. Functions (`broker.py`, all async through `saved._begin()`, every value a bound parameter)

```python
async def lookup_irb(requester: str, q: str) -> IrbLookup
    # latest version per irb_number (distinct_on, as list_irb) WHERE irb_number.istartswith(q, autoescape=True), LIMIT 20
async def register_irb(requester: str, a: IrbCreate) -> IrbStatus
    # SELECT ... FOR UPDATE the existing versions of a.irb_number; version = max + 1 (or 1); status 'active';
    # created_by = requester. Conflict when the requester already has MAX_IRB_VERSIONS rows.
    # The PK makes a concurrent duplicate version an IntegrityError: catch it, raise Conflict("IRB {n} changed; try again").
async def add_irb_document(requester: str, irb_number: str, version: int, d: IrbDocumentCreate) -> IrbStatus
    # NotFound(f"no IRB authorization {irb_number} version {version}") if missing;
    # Conflict(f"IRB {irb_number} version {version} was registered by someone else; register a new version to add documents")
    #   unless created_by == requester; Conflict at MAX_DOCUMENTS. Inserts irb_document(id=uuid4, sha256=NULL, created_by=requester, ...).
async def create_request(requester: str, r: RequestCreate) -> MyRequestDetail
async def update_request(requester: str, id: uuid.UUID, r: RequestDraft) -> MyRequestDetail
async def submit_request(requester: str, signed_as: str, id: uuid.UUID, attestation: str) -> MyRequestDetail
async def delete_request(requester: str, id: uuid.UUID) -> saved.Deleted
```

The helpers:

- `async def _lock_request(conn, requester, id) -> Row`: `SELECT ... FROM request WHERE id = :id AND
  requester = :requester FOR UPDATE`. It raises `NotFound(f"no request {id}")`, the same message
  `get_my_request` uses, so someone else's request looks missing.
- `async def _irb_status(conn, viewer, n, v) -> IrbStatus | None`.
- `async def _missing(conn, r: Request) -> list[str]`.
- `_detail(conn, where, *, broker: bool, viewer: str = "")` gains `viewer` (for `registered_by_you`) and fills
  `attestations` for both views. The requester view also gets `irb` (an `IrbStatus`), `missing`, and
  `attestation` (the text when `missing == []`). The broker view has `missing == []` and `attestation` null: it is not computed there.

Semantics:

- **create_request**:
  1. `head = await saved._lock_head(conn, requester, r.cohort)`. Someone else's cohort, or a missing one,
     raises `NotFound("no saved cohort {id}")`, the existing message (security-r1-1). The lock is the
     cohort row lock, which `saved.delete` now takes too (code-r1-1).
  2. `r.seq > head` raises `NotFound(f"no revision {r.seq}")`.
  3. A requester with `MAX_DRAFTS` rows in `draft` gets `Conflict("at most 20 draft requests per user;
     submit or delete one")`.
  4. Insert `status='draft'`, `purpose=''`, `fields=[]`, `identifiers=[]`, `recipients=[]`,
     `storage_location=''`, IRB and retention NULL.
- **update_request**: lock the row. If the status isn't in `EDITABLE`, raise
  `Conflict(f"request {id} is {status}; only a draft or a returned request can be changed")`. If the IRB
  pair is set and that row doesn't exist, raise `Invalid(f"no IRB authorization {n} version {v}")`.
  If the status is `returned` and the pair or `retention_end` would be NULL, raise `Invalid` (the table's CHECK allows that only on a draft). Otherwise update every editable column (JSON lists via `model_dump(mode="json")`) and set
  `updated_at = now()`. Status is unchanged: a returned request stays `returned` until it is resubmitted.
- **submit_request**: lock the row and check the status as in update. Then:
  1. Compute `missing`. If it isn't empty, raise `Invalid("can't submit yet: " + "; ".join(missing))`.
  2. Render the text. If `text != attestation`, raise `Conflict("the request or its IRB changed since you
     read the attestation; read it again")`.
  3. Insert `request_attestation(id=uuid4, request_id=id, attestation_version, text, signed_by=requester,
     signed_as=signed_as)`.
  4. Set `status='submitted'` and `updated_at=now()`. The status rule is the same for draft → submitted and
     returned → submitted.
- **delete_request**: lock the row. If the status isn't `draft`, raise `Conflict(f"request {id} was
  submitted; it is kept as a record and can't be deleted")`. Otherwise delete it. Drafts have no
  attestations or reviews. Afterwards the saved cohort can be deleted again.

`class Invalid(Exception)` is new in `broker.py` and maps to 400. NotFound, Conflict and Unavailable are
`saved`'s, so the existing 404/409/503 handlers apply.

### 5. Endpoints (`app.py`, REST only)

| route | body | returns | notes |
|---|---|---|---|
| `GET /api/irb?q=` | | `IrbLookup` | `q: Annotated[str, Query(min_length=1, max_length=64)]` |
| `POST /api/irb` | `IrbCreate` | `IrbStatus` | |
| `POST /api/irb/{irb_number}/{version}/documents` | `IrbDocumentCreate` | `IrbStatus` | `irb_number: Annotated[str, Path(pattern=IRB_NUMBER)]`, `version: Annotated[int, Path(ge=1)]` |
| `POST /api/requests` | `RequestCreate` | `MyRequestDetail` | |
| `PUT /api/requests/{id}` | `RequestDraft` | `MyRequestDetail` | |
| `POST /api/requests/{id}/submit` | `SubmitRequest` | `MyRequestDetail` | `signed_as=u.email` |
| `DELETE /api/requests/{id}` | | `Deleted` | draft only |

- Every route uses `Depends(user)` and passes `u.sub`. RequireUser and the terms gate already cover them
  (any signed-in user who has accepted the terms). They are not open routes and not broker routes.
- One handler `@application.exception_handler(broker.Invalid)` returns 400 `{"detail": str(e)}`.
- `INSTRUCTIONS`: the requests sentence becomes "Requests for identified data are created and submitted in
  the browser at /requests; here they are read-only: list_my_requests and get_my_request show the caller's
  own; the broker_* tools are for the honest broker group only." The MCP tools themselves don't change. Only
  `get_my_request`'s output schema changes, through `MyRequestDetail`.
- The static pages: replace the single `/discover` route with a loop over `("discover", "requests")`. Each
  page adds `GET /{page}` → `FileResponse(<static>/{page}.html)` when the file exists (bind the path in a closure
  that takes no parameters: FastAPI exposes any parameter of the endpoint, even a defaulted one such as
  `html=html`, as a query parameter, which would be a file read by query string; a test pins it), with the
  same comment.
- `cd web && bun run gen` regenerates `web/openapi.json` and `web/src/api.gen.ts`, and both are committed.

**What leaves, and the small-cell rule.** None of these routes query the de-id file or return a count. They
return the caller's own request rows, IRB status metadata and the caller's own cohort definitions. The
lookup shows any user the IRB numbers, versions, status, expiry and referenced document types, as the design
asks ("autocompletes known IRB numbers and shows status and expiration"). It never shows PI, population,
personnel or document locations. Free text is guarded against identifier-shaped tokens (§2). No floor
applies because no count is involved. The Discover button sends only the definition, which is what `POST
/api/saved` already accepts.

### 6. The #132 review follow-ups

- **security-r1-1:** `create_request` checks ownership through `saved._lock_head(conn, requester, cohort)`.
  Another user's cohort gets the same 404 and message as a random UUID. Tests are in §Test plan.
- **code-r1-1:** `saved.delete` starts with `await _lock_head(conn, owner, id)`. The lock replaces the join
  to `cohort` in the attached check (`SELECT 1 FROM request WHERE cohort = :id LIMIT 1`), because ownership
  is already established. It raises the same `NotFound` for someone else's cohort and the same `Conflict`.
  `delete` and `create_request` now serialize on the cohort row, so a concurrent insert can no longer turn
  into an IntegrityError (500).
- **code-r1-2:** `MyRequestDetail.irb` becomes `IrbStatus`, trimmed to the design's "status and
  expiration" plus document types. README's "(the IRB's status only, no personnel or documents)" then
  matches what's sent. `docs/specs/132-*.md` gets a "Superseded in part by #133" line at the top saying so.
- **code-r0-2** (still open): `test_revision_snapshot_id` monkeypatches `uccc_genomics_mcp.cohort.snapshot_id`
  with a counter that returns `synthetic-build-1`, `-2` and `-3` on successive calls. It asserts that the
  history's `snapshot_id`s are `[-1, -2, -3]` for save, apply and revert, so a copied id fails. `app.py`
  looks up `cohort.snapshot_id` at call time, which is why the monkeypatch works.

### 7. Discover and the `/requests` page (`web/`)

`transport.ts` stays the only fetch:

```ts
export interface RequestsApi {
  start(definition: Definition): Promise<MyRequestDetail>;  // POST /api/saved, then POST /api/requests {cohort: id, seq: head.seq}
  list(): Promise<Requests>;                                // GET /api/requests
  get(id: string): Promise<MyRequestDetail>;                // GET /api/requests/{id}
  update(id: string, draft: RequestDraft): Promise<MyRequestDetail>;     // PUT /api/requests/{id}
  submit(id: string, attestation: string): Promise<MyRequestDetail>;     // POST /api/requests/{id}/submit
  remove(id: string): Promise<void>;                        // DELETE /api/requests/{id}
  lookupIrb(q: string): Promise<IrbLookup>;                 // GET /api/irb?q=
  registerIrb(a: IrbCreate): Promise<IrbStatus>;            // POST /api/irb
  addDocument(irbNumber: string, version: number, d: IrbDocumentCreate): Promise<IrbStatus>;  // POST /api/irb/{n}/{v}/documents
}
export function fetchRequests(fetchImpl: FetchLike = fetch, signIn = signInAt): RequestsApi   // built on requester(); path segments through encodeURIComponent
```

`types.ts` exports `MyRequestDetail`, `Requests`, `RequestDraft`, `RequestStatus`, `IrbStatus`, `IrbLookup`,
`IrbCreate` and `IrbDocumentCreate` from `api.gen.ts`.

**Discover (`App.tsx`):** `App` takes an optional `requests?: Pick<RequestsApi, "start">`. When it's given,
the header actions (after Feasibility statement, before `Who`) get:

- `<button className="btn-secondary">Request identified data</button>`, disabled while starting. A click
  calls `requests.start(current)` and then `window.location.assign("/requests#" + detail.id)`. A failure
  shows `editError` at `"builder"`: `Could not start a request: ${describeError(e)}`. The `title`/hint is
  "Saves this cohort and opens a request form; identified data comes only from the honest broker".
- `<a className="btn-tertiary" href="/requests">My requests</a>`.

`main.tsx` passes `fetchRequests()`.

**The page:** `web/requests.html` (a copy of `discover.html`, title `My requests · UCCC genomics`,
script `/src/requests-main.tsx`), `src/requests-main.tsx` (renders `<RequestsPage api={fetchRequests()}
account={fetchAccount()} />` in StrictMode), and `vite.config.ts` input `requests: "requests.html"`. The
CSP/GA plugin applies to every input as it is. The new components are `src/Requests.tsx`, with pure helpers
in `src/requests.ts`:

- `requests.ts`: `STATUS_LABEL: Record<RequestStatus, string>`, `STATUS_TEXT` (one sentence per status, e.g.
  submitted → "The honest broker is reviewing this request."), `FIELD_LABEL: Record<RequestField, string>`,
  `IDENTIFIER_LABEL`, `DOC_LABEL`, `toDraft(d: MyRequestDetail): RequestDraft`, and `editable(status)`.
- `RequestsPage({api, account})`: header with "My requests", a link back to `/discover`, and `Who`. The
  header's links stay visible on a phone
  (there is no ⋯ toggle here). The selected request comes from `location.hash` (`#<uuid>`, with a `hashchange` listener). With no
  selection it shows `RequestList`. With one it shows `RequestView`, and a "← All requests" link (`href="#"`).
  Errors go in `role="alert"` with `describeError`; the form scrolls its alert into view, because the buttons
  that fail are far below it. The intro paragraph: "Discover shows counts only.
  Identified data (MRNs, true dates, report ids) comes only from the honest broker, for an active IRB
  approval, delivered to restricted storage."
- `RequestList({requests})`: a table with Cohort (`definition.name` or "Untitled cohort", linked to `#id`),
  Status, IRB (`n v` or "—"), Updated. An empty list says "No requests yet. In Discover, build a cohort and
  choose Request identified data."
- `RequestView({detail, api, onChange})`:
  - The `h2` (focused on open, `tabIndex={-1}`) names the cohort, followed by the status label, the status
    sentence, and a "Cohort" block: cohort_id, snapshot_id, and an "Open in Discover" link to
    `/discover${shareHash(definition)}`.
  - A draft or returned request shows `IntakeForm`. Anything else shows a read-only summary of the same
    fields.
  - "Messages from the honest broker": each review's decision, date and notes, or "None yet".
  - "Releases": date, file name and retention end. "Signed attestations": date and version.
- `IntakeForm({detail, api, onChange})` holds its form state from `toDraft(detail)` and tracks a `dirty`
  flag:
  - **IRB:** a text input `aria-label="IRB number"` with a `<datalist>` filled from `lookupIrb` (debounced
    250 ms, not called for an empty value). A number in the box that matches a suggestion (ignoring case; the box then shows the suggestion's case) is chosen
    whether it was typed, pasted or the lookup returned late (`exactIrb`); when the lookup for the current
    value has no match, a hint says no such IRB is on file and offers registering it. Choosing sets `irb_number` and `irb_version` from the
    lookup's latest version and shows that version's status, expiry and document checklist (✓ or "missing"
    per type). A "Register a new IRB version" toggle opens fields for PI, approval date, expiration date,
    HIPAA pathway and approved population. Its "Register" button calls `registerIrb` and selects the result.
  - **Documents:** for the selected version, when `registered_by_you`, a reference form with a type select,
    title, "Link or location", and section and protocol version (required for the protocol excerpt). Its
    "Add reference" button calls `addDocument` and updates the checklist. When the version isn't yours, the
    hint says "To add documents, register a new version of this IRB." The help text says "Give a link or
    where the document is filed (for example a SharePoint folder). Don't paste patient information."
  - **Fields** checkboxes, **identifiers** (a checkbox each, plus a required reason textarea when it's
    checked), **recipients** (name and email rows with Add and Remove), **storage location**, **retention
    end** (`<input type="date">`) and **purpose** (a textarea). Every control has a visible `<label>`.
  - The buttons: "Save draft" (`btn-secondary`, calls `update`, clears `dirty`) and "Delete draft" (draft
    only, after `window.confirm`, then `location.hash = ""` and reload the list).
  - **Submit block:** when `dirty`, "Save the draft to check it before submitting." Otherwise, when
    `missing.length`, a list headed "Before you can submit:". Otherwise the `attestation` text in a
    `<blockquote>`, a checkbox "I attest to the statement above", and "Submit request" (the one
    `btn-primary`, enabled only when the box is checked). Submitting calls `submit(id, detail.attestation)`.
    On 409 it shows the message and reloads the detail.

The styles reuse the existing tokens and classes (`panel`, `row`, `hint`, `error`, `btn-*`). No new hex
colours (`styles.test.ts` checks).

### 8. Docs (same PR)

- `docs/HONEST_BROKER.md`:
  - Decision 4 becomes: "IRB documents live in SharePoint. The portal records references only (type, title
    or version, link or location). No file passes through the app. The broker files copies with a host
    script outside the app."
  - An "As built (#133)" note under "For requesters": the `/requests` page, document references, the
    attestation stored in `request_attestation`, the portal stopping at submission, closeout not in the
    portal, and `irb_personnel` not entered by requesters.
  - Add `request_attestation` to the as-built data-model note.
- `README.md`, "Honest broker records": rename it to cover the requester flow. List the seven new REST
  routes in one line each, say that the MCP stays read-only for requests, describe the `/requests` page and
  Discover's button, and fix the "IRB's status only" line to "the IRB's status, expiry and referenced
  document types". In the Discover section, mention `requests.html` at `/requests`.
- `docs/ARCHITECTURE.md` decision 7: add "and requester attestations" to the honest-broker table list.
- `AGENTS.md` layout: the `broker.py` line becomes `honest-broker records in Postgres (IRB registry,
  requests, reviews, releases): requester intake and submit; the rest read-only`. The `web/` line adds
  "and My requests (requests.html)".
- `docs/specs/132-*.md`: a "Superseded in part by #133" line (code-r1-2, `sha256` nullable).

**research_id / report_id stability:** unaffected. No pipeline, `deid`, de-id file or hashing change.

## Acceptance criteria

- [ ] `alembic upgrade head` → `downgrade 0003` → `upgrade head` works on the throwaway Postgres. After the
      downgrade, `request_attestation` and `irb_document.title` are gone and `sha256` is NOT NULL.
      `command.check` passes at head.
- [ ] `POST /api/requests` on the caller's own cohort and revision creates a `draft`. On another user's
      cohort it gives 404 with the same body (ids replaced) as a random UUID. A `seq` above head gives 404.
      The 21st draft gives 409.
- [ ] With a raw transaction holding `SELECT ... FOR UPDATE` on a cohort row, `saved.delete` and
      `broker.create_request` both block until it commits. Delete then answers Conflict when the holder
      added a request, and create answers NotFound when the holder deleted the cohort. No IntegrityError
      escapes.
- [ ] `PUT` replaces the editable columns on a draft or returned request, and returns 409 on any other
      status. An unknown IRB pair gives 400. Free text with `1234567` or `TN12-345678` gives 422. Duplicate
      identifiers or recipients give 422. A half-set IRB pair gives 422.
- [ ] `missing` lists exactly the §3 strings for a fresh draft. It is `[]` and `attestation` is the filled-in
      text once the IRB is active and unexpired, the three document types are referenced and the request
      fields are complete. A suspended IRB, an expired IRB and a past retention date each add their string.
- [ ] Submit with `missing` non-empty gives 400 `can't submit yet: ...`. A text that differs by one
      character gives 409. The right text gives `submitted`, one `request_attestation` row with
      `signed_by = sub`, `signed_as = email` and that text, and a later `PUT` gives 409. After a `returned`
      status (set by SQL), editing and submitting again works and adds a second attestation row.
- [ ] `DELETE /api/requests/{id}` deletes a draft (the saved cohort is deletable again) and gives 409 on a
      submitted request. Another user's request gives the same 404 as a missing one for GET, PUT, submit and
      DELETE.
- [ ] `GET /api/irb?q=TEST` returns the latest version per number, with no `pi`, `file_ref`, `approved_population`
      or personnel keys anywhere. `q=T%` matches only numbers that start with `T%` (escaped). `q=` gives 422.
- [ ] `POST /api/irb` creates version 1, then 2. `registered_by_you` is true for the creator and false for
      another user. `POST .../documents` by a non-creator gives 409, a missing version gives 404, and a
      `protocol_excerpt` without a section or protocol version gives 422. A reference row has `sha256 IS NULL`
      and the given `title`.
- [ ] `GET /api/requests/{id}` and `get_my_request` return `irb` with exactly `irb_number, version, status,
      expiration_date, doc_types, registered_by_you`. The broker's `RequestDetail.irb` still has documents
      and personnel.
- [ ] `test_revision_snapshot_id` fails if save, apply or revert stores a copied `snapshot_id`.
- [ ] The new routes and `/requests` are in `GATED` (401 without login). The terms gate applies (403
      `TERMS_REQUIRED` for an unaccepted user on `POST /api/requests`). `/requests` serves `requests.html`.
- [ ] No response from a new route contains `research_id` or a `release_patient` value (the `walk()` check).
- [ ] The web tests below pass. `bun run typecheck` passes with the regenerated `api.gen.ts`.
- [ ] `uv run pytest -q` (with `TEST_DATABASE_URL`) and `cd web && bun install --frozen-lockfile && bun run
      typecheck && bun test` pass. The dashboard check is n/a.

## Test plan

All synthetic: the temp mart from `test_app.mart_file` and the throwaway `TEST_DATABASE_URL`. No test reads
`$DATA/raw`, the PHI file, the real de-id file or the real `DATABASE_URL`. Values are like `TEST-0001`,
`Dr Example`, `r@example.edu` and `synthetic purpose`.

- `tests/test_saved.py`:
  - `clean` adds `request_attestation` to the TRUNCATE.
  - `BROKER_TABLES` gains `request_attestation`.
  - `test_revision_snapshot_id` uses the counter (code-r0-2).
  - New `test_migration_0004_down_and_up` downgrades to `"0003"` and checks the table, the column and
    `sha256` nullability through `information_schema`. It restores head in a `finally`, then runs
    `command.check`.
- `tests/test_broker.py`: a `Writes` helper (REST) for the seven routes, with the existing `x-test-user` /
  `x-test-broker` fake, plus these tests:
  - `test_intake_happy_path`: Rest(A).save → create → registerIrb → three references → PUT a complete draft
    → `missing == []` → submit with `detail["attestation"]` → `submitted`. Then check the attestation row and
    that the text contains `TEST-…`, the section, the protocol version, the storage location and the ISO
    retention date.
  - `test_create_checks_cohort_ownership` (security-r1-1).
  - `test_missing_rules` (parametrized over the §3 cases; the IRB status and expiry are set with `sql()`).
  - `test_submit_refusals` (400, then 409 on changed text, then 409 on a non-editable status).
  - `test_returned_request_can_be_resubmitted`.
  - `test_delete_draft_only`.
  - `test_free_text_guard` (7-digit run, `ID_PATTERN` token, both in `purpose` and a reason → 422).
  - `test_irb_lookup_shape_and_escape`.
  - `test_document_references_by_creator_only`.
  - `test_requester_irb_is_status_only` (code-r1-2): the key set is exact.
  - `test_other_users_request_is_missing` (GET, PUT, submit and DELETE).
  - `test_new_routes_never_carry_a_study_id` (`walk()`).
  - `test_delete_and_create_serialize_on_the_cohort_row` (code-r1-1): one `asyncio.run` coroutine that
    `saved.start(url)`s, creates a cohort with `saved.create`, and opens a separate
    `create_async_engine(url)` connection that runs `SELECT id FROM cohort WHERE id = :id FOR UPDATE`.
    Start `asyncio.create_task(saved.delete(A, id))`, `await asyncio.sleep(0.3)`, assert the task is not
    done, insert a request in the holding transaction, commit, and assert the task raises `saved.Conflict`.
    Repeat with `broker.create_request` against a holder that deletes the cohort: `saved.NotFound`. Call
    `saved.stop()` in `finally`.
  - The existing tests still pass with `irb` now an `IrbStatus`. Update `test_requester_…` assertions that
    read `irb` fields.
- `tests/test_app.py`: `GATED` adds `("GET", "/requests")`, `("GET", "/api/irb?q=x")`, `("POST",
  "/api/irb")` and `("POST", "/api/requests")`. The static fixture writes `requests.html` (`<p>requests</p>`),
  and `test_public_paths_open` asserts `/requests` with auth serves it.
- `tests/test_terms.py`: `POST /api/requests` for an unaccepted user is 403 `TERMS_REQUIRED`.
- `web/src/requests.test.tsx` (bun, `renderToStaticMarkup`, as the other component tests):
  - `RequestList` empty and filled.
  - `RequestView` for draft (form, no read-only summary), submitted (read-only, no form, no Submit) and
    returned (form plus a broker message).
  - The submit block in each of its three states: dirty, missing (list shown, no attestation), and ready
    (blockquote with the text, one `btn-primary`, disabled until checked; static markup shows `disabled`).
  - A version not registered by the caller shows the "register a new version" hint and no reference form.
  - `toDraft` round-trips a detail.
  - Every input has a label.
- `web/src/transport.test.ts`: `fetchRequests` with a fake fetch. `start` posts `/api/saved` then
  `/api/requests` with `{cohort, seq}`, `addDocument` encodes the IRB number, and `remove` sends DELETE.
- `web/src/app.test.tsx`: with `requests` given, the header has "Request identified data" and a
  `/requests` link. Without it, neither.

## Risks

- **Requester-registered IRB versions are self-asserted.** Any terms-accepted user can register a version
  of any IRB number, with status `active`. The broker's checklist (outside the app) is the control. The
  lookup's status is what a requester typed until the broker acts. `created_by` records who did it, and only
  the creator can add references to that version.
- **Document references are unverified text.** A link may be wrong, private or stale, and there is no
  hash. The broker files the real copies in SharePoint from the host. The free-text guard refuses obvious
  identifier shapes but can't stop a person typing a name. `purpose`, reasons and titles are still free text.
- **The free-text guard can refuse legitimate text**, such as a 7-digit grant or protocol number. The 422
  message says why, and the user can rephrase (for example with spaces or dashes). Six-digit NIH serials
  pass.
- **One saved cohort per click.** Each "Request identified data" counts toward `MAX_COHORTS` (100). A
  saved cohort referenced by a request can't be deleted until its draft is deleted. A cohort under a
  submitted request stays forever, by design.
- **Returned requests can't change their cohort.** The requester starts a new request, and the returned one
  stays `returned`. A withdraw status is a later issue.
- **The broker learns of submissions by polling** (`broker_list_requests(status="submitted")`). There's no
  notification.
- **The 0004 downgrade deletes document references** (rows with NULL `sha256`) so that it can restore NOT
  NULL.
- **`seam`/`review:security`:** this changes `saved.delete` (locking), `MyRequestDetail` (an API shape
  regenerated into `web/`), and adds write routes under the terms gate. Existing saved-cohort, broker, app
  and terms tests must keep passing, apart from the `irb` shape updates named above.
