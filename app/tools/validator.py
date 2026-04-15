"""
Onboarding Validator — checks completeness of the employee record
and flags HR-specific issues like missing signatures, invalid formats,
and missing required documents.
"""

from app.models.schemas import EmployeeRecord, DocumentCategory, ProcessedDocument

REQUIRED_DOCUMENTS = [
    DocumentCategory.OFFER_LETTER,
    DocumentCategory.TAX_FORM,
    DocumentCategory.DIRECT_DEPOSIT,
    DocumentCategory.IDENTITY_DOCUMENT,
    DocumentCategory.EMERGENCY_CONTACT,
]

REQUIRED_EMPLOYEE_FIELDS = [
    ("full_name",      "Full Name"),
    ("email",          "Email Address"),
    ("phone",          "Phone Number"),
    ("start_date",     "Start Date"),
    ("job_title",      "Job Title"),
    ("tax_id",         "Tax ID (SIN/SSN)"),
    ("bank_name",      "Bank Name"),
    ("account_number", "Account Number"),
    ("emergency_contact_name",  "Emergency Contact Name"),
    ("emergency_contact_phone", "Emergency Contact Phone"),
]


def validate_onboarding(
    documents: list[ProcessedDocument],
    record: EmployeeRecord,
) -> tuple[list[str], list[str], bool]:
    """
    Returns (missing_documents, critical_flags, ready_for_hris).
    """
    critical_flags = []
    missing_docs   = []

    # Check required document types present
    found_categories = {d.category for d in documents}
    for req in REQUIRED_DOCUMENTS:
        if req not in found_categories:
            label = req.value.replace("_", " ").title()
            missing_docs.append(label)

    # Check required employee fields
    for field_key, field_label in REQUIRED_EMPLOYEE_FIELDS:
        val = getattr(record, field_key, None)
        if not val:
            critical_flags.append(f"Missing: {field_label}")

    # Check signatures
    if record.offer_signed is False:
        critical_flags.append("Offer letter has not been signed")
    if record.policies_acknowledged is False:
        critical_flags.append("Policy acknowledgement is incomplete")

    # Validate tax ID format loosely
    if record.tax_id:
        digits = "".join(c for c in record.tax_id if c.isdigit())
        if len(digits) not in (9,):  # SIN = 9 digits, SSN = 9 digits
            critical_flags.append(f"Tax ID format may be invalid: {record.tax_id}")

    # Ready for HRIS if no critical flags and no missing docs
    ready = len(critical_flags) == 0 and len(missing_docs) == 0

    return missing_docs, critical_flags, ready


def compute_overall_completeness(documents: list[ProcessedDocument]) -> float:
    if not documents:
        return 0.0
    return round(sum(d.completeness_pct for d in documents) / len(documents), 1)