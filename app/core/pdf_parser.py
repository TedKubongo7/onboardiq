"""PDF Parser — extracts raw text from uploaded PDFs."""

import fitz
from fastapi import HTTPException


def parse_pdf(file_bytes: bytes, filename: str) -> dict:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse {filename}: {str(e)}")

    if len(doc) == 0:
        raise HTTPException(status_code=422, detail=f"{filename} has no pages.")

    pages_text = [doc[i].get_text("text") for i in range(len(doc))]
    full_text  = "\n\n".join(pages_text)

    if not full_text.strip():
        raise HTTPException(status_code=422, detail=f"{filename} appears to be empty or image-based.")

    return {
        "filename":   filename,
        "full_text":  full_text,
        "page_count": len(doc),
    }