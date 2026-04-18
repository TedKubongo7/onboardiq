import io
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
import pandas as pd

from app.core.config import settings
from app.core.pdf_parser import parse_pdf
from app.core.spreadsheet_parser import parse_spreadsheet
from app.agents.onboarding_agent import (
    classify_document, extract_document, build_employee_record,
    generate_summary, group_documents_by_employee, CATEGORY_LABELS,
)
from app.tools.validator import validate_onboarding, compute_overall_completeness
from app.models.schemas import (
    OnboardingResult, BatchOnboardingResult, ProcessedDocument, DocumentCategory
)

router = APIRouter(prefix="/api", tags=["onboarding"])


async def _process_document(file: UploadFile) -> ProcessedDocument:
    """Parse, classify, and extract a single PDF, Excel, or CSV file."""
    fname = file.filename.lower()
    allowed = (".pdf", ".xlsx", ".xls", ".csv")
    if not any(fname.endswith(ext) for ext in allowed):
        raise HTTPException(status_code=400, detail=f"{file.filename} is not a supported file type (PDF, Excel, CSV).")
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(status_code=413, detail=f"{file.filename} is too large ({size_mb:.1f} MB).")
    if fname.endswith(".pdf"):
        parsed = parse_pdf(content, file.filename)
    else:
        parsed = parse_spreadsheet(content, file.filename)
    text     = parsed["full_text"]
    category = classify_document(text)
    fields, issues, completeness = extract_document(text, category)
    return ProcessedDocument(
        filename=file.filename,
        category=category,
        category_label=CATEGORY_LABELS.get(category, "Unknown Document"),
        fields=fields,
        completeness_pct=completeness,
        issues=issues,
        raw_text=text[:1500],
    )


def _build_result(documents: list[ProcessedDocument]) -> OnboardingResult:
    """Build a complete OnboardingResult from a list of processed documents."""
    employee_record  = build_employee_record(documents)
    missing_docs, critical_flags, ready = validate_onboarding(documents, employee_record)
    overall_completeness = compute_overall_completeness(documents)
    summary = generate_summary(
        employee_record, documents, overall_completeness,
        critical_flags, missing_docs, ready,
    )
    return OnboardingResult(
        documents=documents,
        employee_record=employee_record,
        overall_completeness=overall_completeness,
        missing_documents=missing_docs,
        critical_flags=critical_flags,
        ready_for_hris=ready,
        summary=summary,
    )


@router.post("/process", response_model=BatchOnboardingResult)
async def process_onboarding(files: List[UploadFile] = File(...)):
    """
    Upload 1–20 onboarding PDFs for one or more employees.
    AI groups documents by employee name and processes each group separately.
    """
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files per submission.")

    # Step 1: Parse and extract all documents
    all_documents: list[ProcessedDocument] = []
    for file in files:
        doc = await _process_document(file)
        all_documents.append(doc)

    # Step 2: Group by employee
    groups = group_documents_by_employee(all_documents)

    # Step 3: Build result for each employee
    results: list[OnboardingResult] = []
    for employee_name, docs in groups.items():
        result = _build_result(docs)
        results.append(result)

    ready_count     = sum(1 for r in results if r.ready_for_hris)
    not_ready_count = len(results) - ready_count

    return BatchOnboardingResult(
        employees=results,
        total_employees=len(results),
        ready_count=ready_count,
        not_ready_count=not_ready_count,
    )


@router.post("/export")
async def export_records(data: dict):
    """Export all employee records as Excel — one row per employee."""
    employees = data.get("employees", [])
    if not employees:
        raise HTTPException(status_code=400, detail="No employee data to export.")

    # Build flat rows
    rows = []
    for emp in employees:
        record = emp.get("employee_record", {})
        row = {k.replace("_", " ").title(): v for k, v in record.items() if v is not None}
        row["Ready for HRIS"] = "Yes" if emp.get("ready_for_hris") else "No"
        row["Completeness %"] = emp.get("overall_completeness", 0)
        rows.append(row)

    df_records = pd.DataFrame(rows)

    # Build completeness sheet
    comp_rows = []
    for emp in employees:
        name = emp.get("employee_record", {}).get("full_name", "Unknown")
        for doc in emp.get("documents", []):
            comp_rows.append({
                "Employee":    name,
                "Document":    doc.get("category_label", ""),
                "File":        doc.get("filename", ""),
                "Completeness": f"{doc.get('completeness_pct', 0)}%",
                "Issues":      "; ".join(doc.get("issues", [])) or "None",
            })
    df_completeness = pd.DataFrame(comp_rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_records.to_excel(writer, sheet_name="Employee Records", index=False)
        df_completeness.to_excel(writer, sheet_name="Document Completeness", index=False)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="onboarding_batch.xlsx"'},
    )


@router.get("/health")
async def health():
    return {"status": "ok"}