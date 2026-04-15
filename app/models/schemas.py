from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum


class DocumentCategory(str, Enum):
    OFFER_LETTER       = "offer_letter"
    TAX_FORM           = "tax_form"
    DIRECT_DEPOSIT     = "direct_deposit"
    IDENTITY_DOCUMENT  = "identity_document"
    EMERGENCY_CONTACT  = "emergency_contact"
    POLICY_ACKNOWLEDGEMENT = "policy_acknowledgement"
    UNKNOWN            = "unknown"


class FieldStatus(str, Enum):
    COMPLETE  = "complete"
    MISSING   = "missing"
    FLAGGED   = "flagged"


class DocumentField(BaseModel):
    key: str
    label: str
    value: Optional[str] = None
    status: FieldStatus = FieldStatus.MISSING
    flag_reason: Optional[str] = None


class ProcessedDocument(BaseModel):
    filename: str
    category: DocumentCategory
    category_label: str
    fields: list[DocumentField]
    completeness_pct: float
    issues: list[str]
    raw_text: Optional[str] = None


class EmployeeRecord(BaseModel):
    # Personal info
    full_name: Optional[str] = None
    preferred_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    province_state: Optional[str] = None
    postal_zip: Optional[str] = None
    country: Optional[str] = None

    # Employment info
    job_title: Optional[str] = None
    department: Optional[str] = None
    start_date: Optional[str] = None
    employment_type: Optional[str] = None
    salary: Optional[str] = None
    manager_name: Optional[str] = None
    work_location: Optional[str] = None

    # Tax & payroll
    tax_id: Optional[str] = None          # SIN or SSN
    tax_form_type: Optional[str] = None   # TD1 or W-4
    filing_status: Optional[str] = None
    allowances: Optional[str] = None

    # Banking
    bank_name: Optional[str] = None
    account_type: Optional[str] = None
    transit_routing: Optional[str] = None
    account_number: Optional[str] = None

    # Emergency contact
    emergency_contact_name: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    # Signatures & acknowledgements
    offer_signed: Optional[bool] = None
    policies_acknowledged: Optional[bool] = None
    signature_date: Optional[str] = None


class OnboardingResult(BaseModel):
    documents: list[ProcessedDocument]
    employee_record: EmployeeRecord
    overall_completeness: float
    missing_documents: list[str]
    critical_flags: list[str]
    ready_for_hris: bool
    summary: str


class BatchOnboardingResult(BaseModel):
    employees: list[OnboardingResult]
    total_employees: int
    ready_count: int
    not_ready_count: int