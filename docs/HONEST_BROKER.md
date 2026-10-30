# Honest Broker Process for Clinical Genomics Re-identification

Oct 30, 2026 · @Sean Davis
> **Status and decisions (2026-10-30).** This is the design record for Tier 2 (#16). Tier 1 is
> the campus Discover app (`docs/ARCHITECTURE.md`). Sean's decisions on points where this draft
> and the built system differ:
>
> 1. **Tier 1 shows counts only.** No row-level data and no "small samples" or "capped sample":
>    every Tier 1 output is a floored aggregate (`dashboard/COHORT_DISCOVERY.md` §3.6). Where the
>    text below says "counts and small samples" or "a capped sample", read "counts".
> 2. **Study IDs stay keyed hashes.** `research_id` is a keyed hash (HMAC-style, key in
>    `$DATA/.deid_key`) of the normalized MRN, or of name and DOB when the MRN is missing. Without
>    the key it cannot be reversed or recomputed; the key plays the role of the crosswalk and
>    lives only in the secure environment. "Randomly assigned, never derived from MRNs" below is
>    superseded by this.
> 3. **The Tier 1 gate is terms acceptance.** Campus sign-in (Authentik, `@cuanschutz.edu`
>    Google accounts) plus acceptance of the portal terms at first login, recorded per user.
> 4. **IRB documents live in SharePoint.** The portal records references only (type, title or
>    version, and a link or location the requester gives). No file passes through the app, which
>    has no SharePoint access. The broker files copies in SharePoint with a host script outside the
>    app. (Supersedes the earlier "written with rclone by a server-side uploader"; #133.)
> 5. **One SharePoint folder per request**, reused for refreshes of that request. Granting named
>    recipients access programmatically (Microsoft Graph) is unverified; until it is, the broker
>    shares the folder by hand and the system records it.
> 6. **Build notes below are superseded:** the store is DuckDB (not Parquet), and Tier 1 is the
>    custom portal, so the request and review layer is part of the same app.
>
> Implementation issues: listed in #16.


## Purpose and scope

Identifiable data from the clinical genomics database (Caris and Foundation Medicine results) leaves only through the honest broker, only to investigators on an active IRB authorization, and every release traces to that authorization. Investigators never run queries against identified data themselves.

Access has two tiers:

| Tier | What the user sees | Gate | Records kept |
| --- | --- | --- | --- |
| 1. De-identified perusal | Date-shifted, de-identified data in the portal; counts and small samples only | Approved cancer center member, signed portal terms | Login and query log |
| 2. Honest-broker release | Identified results (MRNs, true dates, report IDs) delivered to a restricted SharePoint folder | Approved request tied to an active IRB authorization | Request, IRB authorization, review, release, closeout |

Roles:

- **Requester** is the PI or study staff named on the IRB approval. They build the cohort in Tier 1 and submit the request.
- **Honest broker** (Sean Davis, plus a named backup) holds the crosswalk from study IDs to MRNs, reviews requests, runs the approved query against identified data, and delivers results.
- **Privacy office and COMIRB** are consulted on unclear HIPAA pathways; they are not in the routine path.

Out of scope: bulk exports, recurring feeds, and releases to parties outside the institution. Each of those needs its own agreement and is handled case by case.

## Process

A request moves from cohort to closeout in seven steps. The target turnaround is 10 business days from a complete submission.

1. **Build the cohort in the portal.** The requester defines the cohort in Tier 1 and saves the query. The saved query is frozen with its hash and the database snapshot it ran against.
2. **Register or select the IRB authorization.** The requester enters the IRB number. If it is new to the system, they register it and reference (type, title or version, and a link or location; nothing is uploaded):
   - the current IRB approval letter or determination;
   - the approved personnel list;
   - the protocol excerpt that justifies the request, cited by section and page, with the protocol version;
   - the consent and HIPAA authorization form, when the release relies on consent. Later requests under the same IRB number reuse this record until it expires or is amended.
3. **Submit the request.** It attaches the frozen query and states the purpose, the fields wanted, the identifiers wanted with a reason for each, who will access the results, and the retention and destruction plan.
4. **Broker review.** The broker completes the review checklist below and records one of three decisions: approve, return for changes, or deny. Unclear HIPAA pathways go to the privacy office before a decision.
5. **Fulfillment.** The broker reruns the frozen query against identified data and joins the crosswalk. Output is limited to the approved fields. The broker places it in a request-specific SharePoint folder shared only with the named recipients, with a release cover note.
6. **Release logging.** The system records the file name and checksum, row count, fields released, recipients, date, and the folder link. This is the record that answers "where did the data go."
7. **Closeout.** At the end of the stated retention period, or when the IRB approval lapses, the requester attests to destruction or to transfer into the approved study system. The broker then removes the SharePoint share.

### Review checklist

- [ ] Requester and all recipients appear on the approved personnel list
- [ ] IRB approval is active today and will remain active through the planned use
- [ ] The cohort definition matches the approved population, such as diagnosis, site, and date range
- [ ] The HIPAA pathway covers this use, for example recruitment contact or chart review
- [ ] Each identifier requested traces to approved protocol language (minimum necessary)
- [ ] A coded or limited data set alternative has been considered and declined for a stated reason
- [ ] The destination and retention plan match the protocol

### Renewal and amendments

The system flags authorizations 30 days before expiration and blocks new releases after it. An amended protocol or personnel change requires referencing the new documents; earlier releases keep their link to the version that was in force.

## Policy and form language

The draft language below is ready to adapt. It should be reviewed by the privacy office before use.

### Portal terms (Tier 1, accepted at first login)

> The clinical genomics portal contains de-identified, date-shifted data belonging to \[health system\] and made available through the University of Colorado Cancer Center. Access is limited to approved cancer center members for research planning, feasibility, and cohort discovery. By using the portal, I agree not to attempt to identify any individual, link portal data with other sources to re-identify individuals, or share screenshots or exports beyond my study team. Identifiable data is available only through an approved honest-broker request tied to an active IRB authorization. Queries are logged.

As built (#131): the text is `TERMS_TEXT` in `mcp/src/uccc_genomics_mcp/terms.py`, with `[health system]` = UCHealth (pending privacy-office review), version `TERMS_VERSION`; acceptance is `terms_acceptance(sub, terms_version, accepted_at)`.

### Access policy statement

> Identifiable information derived from the clinical genomics database, including medical record numbers, true dates, and vendor report identifiers, is released only by the designated honest broker. Each release must be supported by an active IRB approval, a HIPAA pathway that covers the intended use, and protocol language that justifies each identifier requested. Releases are delivered to access-restricted storage, are logged, and must be destroyed or transferred to an approved study system at the end of the stated retention period.

### Requester attestation (signed on each request)

> I attest that I and all named recipients are listed on the IRB approval for protocol \[IRB number\], that the approval is active, and that the data requested is the minimum necessary for the purpose described, which is approved in section \[section\] of protocol version \[version\]. I will use the data only for that purpose. I will not share it beyond the named recipients, re-disclose it, or link it to other data except as the protocol permits. I will store it only in \[approved location\], and I will destroy it or transfer it to the approved study system by \[date\]. I will notify the honest broker within 24 hours of any suspected unauthorized access or disclosure.

### Release cover note (placed in the SharePoint folder)

> This folder contains identifiable data released under IRB \[number\], request \[ID\], on \[date\]. It contains \[n\] records with these fields: \[fields\]. Access is limited to \[names\]. Do not copy this data outside approved storage. The retention period ends \[date\], when the share will be removed. Questions go to the honest broker at \[contact\].

## Portal features

The portal makes the saved query the unit of work. The same query a requester sees counts for in Tier 1 is the query the broker reruns, so approval and fulfillment refer to one exact definition.

### For requesters

- **Cohort builder** filters on diagnosis, tumor site, gene and variant, biomarkers (MSI, TMB, PD-L1), vendor, and shifted date ranges. It shows counts, with small cells suppressed below a set threshold, and a capped sample.
- **Saved queries** carry a canonical form, a hash, the snapshot ID, the author, and a plain-language description. Editing a saved query creates a new version rather than changing the old one.
- **Request identification** is a button on any saved query. It opens the intake form with the query attached and prompts for the IRB number.
- **IRB registry lookup** autocompletes known IRB numbers and shows status and expiration. It lets the requester register a new or amended authorization and reference its documents.
- **My requests** shows status (draft, submitted, returned, approved, fulfilled, closed), messages from the broker, release dates, and retention deadlines with closeout attestation.

As built (#133): the requester flow is the `/requests` page (`web/requests.html`), reached from Discover's
**Request identified data** button, which saves the current definition as a new saved cohort and opens a draft
on its first revision. The portal goes as far as **submission**: it never shows sample rows or anything
identified, and review, fulfillment, exports and deliveries run outside the app. Any signed-in user who has
accepted the portal terms may request; the broker's IRB personnel check is the gate. The intake records each IRB
document as a reference (type, title or version, link or location); the requester can add references only to
an IRB version they registered, and the broker files copies in SharePoint with a host script. The requester
attestation is filled in from the request, shown, and stored with the text signed. The closeout attestation is
not in the portal (#136), and `irb_personnel` is not entered by requesters: the broker transcribes it from the
referenced personnel list, if at all. MCP stays read-only for requests.

### For the honest broker

- **Review queue** shows each request beside its IRB authorization, the uploaded documents, the frozen query, and its current count, with the checklist inline.
- **Fulfillment runner** executes the frozen query against identified data inside the secure environment, applies the approved field list, writes the output file and checksum, and records the SharePoint folder link.
- **Expiration and closeout dashboard** lists authorizations nearing expiration, overdue closeouts, and open shares.
- **Release ledger** is searchable by IRB number, requester, patient study ID, or date range. Searching by patient answers "which releases included this person," which supports disclosure accounting.

### Safeguards built into Tier 1

- Small-cell suppression and sample caps.
- Query rate limits and logging to detect differencing attacks, meaning repeated narrow queries that isolate individuals.
- Study IDs randomly assigned, never derived from MRNs or other identifiers, with the crosswalk stored outside the portal.
- Consistent per-patient date shifts so intervals stay accurate while calendar dates do not leak.

### Build notes

A custom portal over the existing Parquet files supports this workflow directly. cBioPortal could still serve as the Tier 1 viewer, but it has no concept of a saved, hashed query tied to a request, so the request and review layer would sit beside it as a separate small app.

## Data model

Nine tables carry the whole audit trail. A release joins to exactly one request, one IRB authorization version, and one frozen query, so any release can be explained from the database alone.

| Table | Key fields | Notes |
| --- | --- | --- |
| irb\_authorization | irb\_number, version, pi, approval\_date, expiration\_date, hipaa\_pathway, approved\_population, status | One row per approval version; amendments add rows |
| irb\_document | irb\_number, version, doc\_type, file\_ref, sha256, section\_cited, protocol\_version | Letter, personnel list, protocol excerpt, consent form |
| irb\_personnel | irb\_number, version, person\_id, role | Checked against requester and recipients |
| saved\_query | query\_id, version, canonical\_sql, sha256, snapshot\_id, author, description | Immutable once attached to a request |
| request | request\_id, query\_id, query\_version, irb\_number, irb\_version, requester, purpose, fields, identifiers\_with\_reason, recipients, storage\_location, retention\_end, status | Status runs draft to closed |
| review | request\_id, reviewer, checklist\_json, decision, notes, decided\_at | One or more per request |
| release | release\_id, request\_id, file\_name, sha256, row\_count, fields\_released, recipients, sharepoint\_link, released\_at, removed\_at, closeout\_attested\_at | The answer to "where did the data go" |
| release\_patient | release\_id, study\_id | Supports per-patient disclosure accounting; MRNs are not stored here |

As built in #133: `request_attestation` is a ninth table (`request_id`, `attestation_version`, `text`, `signed_by`
= `sub`, `signed_as` = email, `signed_at`), one row for each signature of the requester attestation, kept for
every submission of a request. `irb_document` gains `title`, and `sha256` is nullable: a document the requester
referenced has no hash because no file passes through the app.

As built in #132 (`mcp/src/uccc_genomics_mcp/broker.py`, migration `0002`): `saved_query` is not a table, it
maps onto `cohort_revision` (`query_id` = `cohort.id`, `version` = `seq`, `canonical_sql` = the canonical
definition JSON, `sha256` = `cohort_id`, `snapshot_id` = the new `cohort_revision.snapshot_id`, `author` =
`cohort.owner`, `description` = `definition.name`). `release_patient.study_id` is `research_id`.
`request.status` adds `denied`. `irb_authorization.status` is `active|suspended|closed`; "expired" is derived
from `expiration_date`, never stored. The build id is `meta.build.build_id` in the de-id file.

The crosswalk from study ID to MRN lives only in the secure environment, outside these tables. The portal and its logs never hold MRNs.

## Open questions for COMIRB and the privacy office

- [ ] Does a treating oncologist screening their own patients for a trial count as clinical operations or research? This decides whether trial pre-screening requests need a partial HIPAA waiver.
- [ ] Which HIPAA pathways will the broker accept without escalation, and which always go to the privacy office?
- [ ] Does the date-shifted, de-identified Tier 1 data meet Safe Harbor, or should it be documented under expert determination?
- [ ] Is the broker's per-release log sufficient for accounting of disclosures under 45 CFR 164.528, or is a central institutional log also required?
- [ ] Is the SharePoint site approved for identifiable research data, and who can audit its sharing settings?
- [ ] Who serves as backup honest broker, and what training do they need?
- [ ] What small-cell threshold and sample cap should Tier 1 use?
