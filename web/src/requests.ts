import type { DocType, Identifier, IrbStatus, MyRequestDetail, RequestDraft, RequestField, RequestStatus } from "./types.ts";

export const STATUS_LABEL: Record<RequestStatus, string> = {
  draft: "Draft", submitted: "Submitted", returned: "Returned", approved: "Approved", denied: "Denied",
  fulfilled: "Fulfilled", closed: "Closed",
};

export const STATUS_TEXT: Record<RequestStatus, string> = {
  draft: "Not submitted yet. Fill in the form and sign the attestation.",
  submitted: "The honest broker is reviewing this request.",
  returned: "The honest broker returned this request with a message. Change it and submit it again.",
  approved: "The honest broker approved this request. Delivery happens outside this site.",
  denied: "The honest broker did not approve this request.",
  fulfilled: "The data was delivered to the recipients' restricted storage.",
  closed: "This request is closed.",
};

export const FIELD_LABEL: Record<RequestField, string> = {
  demographics: "Demographics", diagnosis: "Diagnosis", specimen: "Specimen", test: "Test", variants: "Variants",
  copy_number: "Copy number", fusions: "Fusions", biomarkers: "Biomarkers", ihc: "IHC", expression: "Expression",
  genes_tested: "Genes tested",
};

export const IDENTIFIER_LABEL: Record<Identifier, string> = {
  mrn: "MRN", name: "Patient name", dob: "Date of birth", true_dates: "True (unshifted) dates",
  vendor_report_id: "Vendor report id",
};

export const DOC_LABEL: Record<DocType, string> = {
  approval_letter: "IRB approval letter", personnel_list: "Approved personnel list",
  protocol_excerpt: "Protocol excerpt", consent_form: "Consent / HIPAA form (when relevant)",
};

export const editable = (status: RequestStatus): boolean => status === "draft" || status === "returned";

/** The editable columns of a request, as the PUT body. */
export function toDraft(d: MyRequestDetail): RequestDraft {
  return {
    irb_number: d.irb_number ?? null, irb_version: d.irb_version ?? null, purpose: d.purpose,
    fields: d.fields as RequestField[], identifiers: d.identifiers.map((i) => ({...i})),
    recipients: d.recipients.map((r) => ({...r})), storage_location: d.storage_location,
    retention_end: d.retention_end ?? null,
  };
}

/** The suggestion that is the number in the box (ignoring surrounding spaces and case), if any. */
export const exactIrb = (options: IrbStatus[], query: string): IrbStatus | undefined =>
  options.find((o) => o.irb_number.toLowerCase() === query.trim().toLowerCase());
