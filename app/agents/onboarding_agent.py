"""
Onboarding Agent — uses Claude to:
1. Classify each document type
2. Extract structured fields from each document
3. Assemble a unified employee record via direct field mapping
4. Generate a plain-English onboarding summary
"""

import re
import json
import anthropic
from app.core.config import settings
from app.models.schemas import (
    DocumentCategory, DocumentField, FieldStatus,
    ProcessedDocument, EmployeeRecord
)

CATEGORY_LABELS = {
    DocumentCategory.OFFER_LETTER:           "Offer Letter",
    DocumentCategory.TAX_FORM:               "Tax Form (TD1/W-4)",
    DocumentCategory.DIRECT_DEPOSIT:         "Direct Deposit Form",
    DocumentCategory.IDENTITY_DOCUMENT:      "Identity Document",
    DocumentCategory.EMERGENCY_CONTACT:      "Emergency Contact Form",
    DocumentCategory.POLICY_ACKNOWLEDGEMENT: "Policy Acknowledgement",
    DocumentCategory.UNKNOWN:                "Unknown Document",
}

DOCUMENT_FIELDS = {
    DocumentCategory.OFFER_LETTER: [
        ("employee_name",   "Employee Name"),
        ("job_title",       "Job Title"),
        ("department",      "Department"),
        ("start_date",      "Start Date"),
        ("salary",          "Salary / Compensation"),
        ("employment_type", "Employment Type"),
        ("manager_name",    "Reporting Manager"),
        ("work_location",   "Work Location"),
        ("offer_signed",    "Signed by Employee"),
        ("signature_date",  "Signature Date"),
    ],
    DocumentCategory.TAX_FORM: [
        ("employee_name",   "Employee Name"),
        ("tax_id",          "Tax ID (SIN/SSN)"),
        ("date_of_birth",   "Date of Birth"),
        ("address",         "Home Address"),
        ("filing_status",   "Filing Status"),
        ("allowances",      "Allowances / Exemptions"),
        ("tax_form_type",   "Form Type (TD1/W-4)"),
        ("signature_date",  "Signature Date"),
    ],
    DocumentCategory.DIRECT_DEPOSIT: [
        ("employee_name",   "Employee Name"),
        ("bank_name",       "Bank Name"),
        ("account_type",    "Account Type"),
        ("transit_routing", "Transit/Routing Number"),
        ("account_number",  "Account Number"),
        ("signature_date",  "Signature Date"),
    ],
    DocumentCategory.IDENTITY_DOCUMENT: [
        ("full_name",       "Full Legal Name"),
        ("date_of_birth",   "Date of Birth"),
        ("id_type",         "Document Type"),
        ("id_number",       "Document Number"),
        ("expiry_date",     "Expiry Date"),
        ("issuing_country", "Issuing Country/State"),
    ],
    DocumentCategory.EMERGENCY_CONTACT: [
        ("employee_name",                 "Employee Name"),
        ("email",                         "Personal Email"),
        ("phone",                         "Personal Phone"),
        ("emergency_contact_name",        "Emergency Contact Name"),
        ("emergency_contact_relationship","Relationship"),
        ("emergency_contact_phone",       "Contact Phone"),
        ("emergency_contact_email",       "Contact Email"),
    ],
    DocumentCategory.POLICY_ACKNOWLEDGEMENT: [
        ("employee_name",          "Employee Name"),
        ("policies_acknowledged",  "Policies Acknowledged"),
        ("signature_date",         "Signature Date"),
    ],
}

DEFAULT_FIELDS = [
    ("employee_name", "Employee Name"),
    ("document_date", "Document Date"),
]


CLASSIFY_PROMPT = """You are an HR document specialist. Classify this document into one of these categories:
- offer_letter
- tax_form
- direct_deposit
- identity_document
- emergency_contact
- policy_acknowledgement
- unknown

Document text:
{text}

Reply with ONLY the category name, nothing else."""


EXTRACT_PROMPT = """You are an expert HR document processor. Extract structured data from this {doc_type} document.

Document text:
{text}

Extract these fields and return ONLY valid JSON — no markdown, no explanation:
{{
  "fields": [
    {fields_list}
  ],
  "issues": ["list any problems found, e.g. missing signature, expired ID, illegible field"],
  "completeness_pct": <number 0-100>
}}

For each field use this structure:
{{"key": "field_key", "label": "Field Label", "value": "extracted value or null", "status": "complete|missing|flagged", "flag_reason": "reason if flagged or null"}}

Rules:
- status = "complete" if value is clearly present
- status = "missing" if field not found in document
- status = "flagged" if value is present but suspicious (e.g. expired date, wrong format)
- Be conservative — mark uncertain values as "flagged" not "complete"
- For boolean fields like "offer_signed", value should be "true" or "false"
- Keep the EXACT key names as specified — do not rename them"""


SUMMARY_PROMPT = """You are an HR onboarding coordinator. Write a 3-4 sentence plain-English summary of this onboarding packet.

Employee: {name}
Documents received: {doc_list}
Overall completeness: {completeness}%
Critical flags: {flags}
Missing documents: {missing}
Ready for HRIS: {ready}

Be direct and professional. State whether the packet is ready to process, what's missing, and what action is needed."""


# ── Document classification ────────────────────────────────────────────────────

def classify_document(text: str) -> DocumentCategory:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.model,
        max_tokens=50,
        messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(text=text[:3000])}],
    )
    raw = response.content[0].text.strip().lower()
    try:
        return DocumentCategory(raw)
    except ValueError:
        return DocumentCategory.UNKNOWN


# ── Field extraction ───────────────────────────────────────────────────────────

def extract_document(text: str, category: DocumentCategory) -> tuple[list[DocumentField], list[str], float]:
    client  = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    fields  = DOCUMENT_FIELDS.get(category, DEFAULT_FIELDS)
    fields_list = "\n    ".join(
        f'{{"key": "{k}", "label": "{l}", "value": null, "status": "missing", "flag_reason": null}}'
        for k, l in fields
    )
    prompt = EXTRACT_PROMPT.format(
        doc_type=CATEGORY_LABELS.get(category, "document"),
        text=text[:5000],
        fields_list=fields_list,
    )
    response = client.messages.create(
        model=settings.model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], ["Could not parse document"], 0.0

    doc_fields = []
    for item in data.get("fields", []):
        raw_val = item.get("value")
        if isinstance(raw_val, list):
            str_val = ", ".join(str(v) for v in raw_val)
        elif raw_val is not None:
            str_val = str(raw_val).strip()
        else:
            str_val = None

        doc_fields.append(DocumentField(
            key=item.get("key", ""),
            label=item.get("label", ""),
            value=str_val,
            status=FieldStatus(item.get("status", "missing")),
            flag_reason=item.get("flag_reason"),
        ))

    issues       = data.get("issues", [])
    completeness = float(data.get("completeness_pct", 0))
    return doc_fields, issues, completeness


# ── Address parsing helpers ────────────────────────────────────────────────────

def _parse_address_part(address: str | None, part: str) -> str | None:
    if not address:
        return None

    if part == "postal":
        match = re.search(r'\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b', address, re.IGNORECASE)
        return match.group(0).upper() if match else None

    parts = [p.strip() for p in address.split(",")]

    if part == "city" and len(parts) >= 2:
        return parts[-2].strip() if len(parts) >= 3 else parts[1].strip()

    if part == "province" and len(parts) >= 2:
        last    = parts[-1].strip()
        cleaned = re.sub(r'\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b', '', last, flags=re.IGNORECASE).strip()
        if cleaned:
            return cleaned
        return parts[-2].strip() if len(parts) >= 3 else None

    return None


def _parse_country(address: str | None) -> str | None:
    if not address:
        return None
    address_upper = address.upper()

    if re.search(r'\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b', address_upper):
        return "Canada"
    if re.search(r'\b\d{5}(?:-\d{4})?\b', address):
        return "United States"

    ca_provinces = ["ON","BC","AB","QC","MB","SK","NS","NB","NL","PE","NT","YT","NU"]
    for prov in ca_provinces:
        if re.search(rf'\b{prov}\b', address_upper):
            return "Canada"

    us_states = [
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
        "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
        "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
        "TX","UT","VT","VA","WA","WV","WI","WY","DC"
    ]
    for state in us_states:
        if re.search(rf'\b{state}\b', address_upper):
            return "United States"

    return None


# ── Employee record assembly ───────────────────────────────────────────────────

def build_employee_record(documents: list[ProcessedDocument]) -> EmployeeRecord:
    """
    Build employee record by directly mapping extracted fields.
    Takes the longest/most complete value for each key across all documents.
    """
    all_fields: dict[str, str] = {}
    for doc in documents:
        for f in doc.fields:
            if not f.value:
                continue
            val = str(f.value).strip()
            if not val or val.lower() in ("not found", "null", "none", "n/a"):
                continue
            existing = all_fields.get(f.key, "")
            if len(val) >= len(existing):
                all_fields[f.key] = val

    def get(*keys: str) -> str | None:
        for k in keys:
            v = all_fields.get(k)
            if v:
                return v
        return None

    def parse_bool(val: str | None) -> bool | None:
        if val is None:
            return None
        return str(val).lower() in ("true", "yes", "1", "signed", "acknowledged")

    address = get("address", "home_address")

    return EmployeeRecord(
        full_name=get("full_name", "employee_name"),
        preferred_name=get("preferred_name"),
        date_of_birth=get("date_of_birth"),
        email=get("email", "personal_email"),
        phone=get("phone", "personal_phone"),
        address=address,
        city=_parse_address_part(address, "city") or get("city"),
        province_state=_parse_address_part(address, "province") or get("province_state", "province", "state"),
        postal_zip=_parse_address_part(address, "postal") or get("postal_zip", "postal_code"),
        country=get("country") or _parse_country(address),
        job_title=get("job_title"),
        department=get("department"),
        start_date=get("start_date"),
        employment_type=get("employment_type"),
        salary=get("salary"),
        manager_name=get("manager_name", "reporting_manager"),
        work_location=get("work_location"),
        tax_id=get("tax_id", "sin", "ssn"),
        tax_form_type=get("tax_form_type", "form_type"),
        filing_status=get("filing_status"),
        allowances=get("allowances"),
        bank_name=get("bank_name"),
        account_type=get("account_type"),
        transit_routing=get("transit_routing", "transit_number", "routing_number"),
        account_number=get("account_number"),
        emergency_contact_name=get("emergency_contact_name", "contact_name"),
        emergency_contact_relationship=get("emergency_contact_relationship", "relationship"),
        emergency_contact_phone=get("emergency_contact_phone", "contact_phone"),
        offer_signed=parse_bool(get("offer_signed")),
        policies_acknowledged=parse_bool(get("policies_acknowledged")),
        signature_date=get("signature_date"),
    )


# ── Summary generation ─────────────────────────────────────────────────────────

def generate_summary(
    record: EmployeeRecord,
    documents: list[ProcessedDocument],
    completeness: float,
    critical_flags: list[str],
    missing_docs: list[str],
    ready: bool,
) -> str:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = SUMMARY_PROMPT.format(
        name=record.full_name or "Unknown Employee",
        doc_list=", ".join(d.category_label for d in documents),
        completeness=completeness,
        flags="; ".join(critical_flags) if critical_flags else "None",
        missing=", ".join(missing_docs) if missing_docs else "None",
        ready="Yes" if ready else "No",
    )
    response = client.messages.create(
        model=settings.model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── Document grouping ──────────────────────────────────────────────────────────

def group_documents_by_employee(documents: list[ProcessedDocument]) -> dict[str, list[ProcessedDocument]]:
    """
    Group documents by employee name using fuzzy name matching.
    Returns dict of {display_name: [documents]}
    """

    def extract_name(doc: ProcessedDocument) -> str | None:
        for field in doc.fields:
            if field.key in ("employee_name", "full_name") and field.value:
                val = str(field.value).strip()
                if val.lower() not in ("not found", "null", "none", "n/a"):
                    return val
        return None

    def normalize_name(name: str) -> str:
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', name.lower())).strip()

    groups:   dict[str, list[ProcessedDocument]] = {}
    name_map: dict[str, str] = {}

    for doc in documents:
        raw_name = extract_name(doc)
        if not raw_name:
            key = "unknown_employee"
            name_map.setdefault(key, "Unknown Employee")
        else:
            norm        = normalize_name(raw_name)
            matched_key = None

            for existing_norm in name_map:
                if existing_norm == norm:
                    matched_key = existing_norm
                    break
                existing_parts = set(existing_norm.split())
                new_parts      = set(norm.split())
                if len(existing_parts & new_parts) >= 2:
                    matched_key = existing_norm
                    break

            if matched_key:
                key = matched_key
            else:
                key = norm
                name_map[norm] = raw_name

        groups.setdefault(key, []).append(doc)

    return {name_map.get(k, k.title()): docs for k, docs in groups.items()}