"""Spreadsheet Parser — converts Excel and CSV files to text for AI extraction."""

import io
import pandas as pd
from fastapi import HTTPException


def parse_spreadsheet(file_bytes: bytes, filename: str) -> dict:
    """
    Read an Excel or CSV file and convert its contents to a text representation.
    Returns the same dict shape as parse_pdf for drop-in compatibility.
    """
    fname_lower = filename.lower()

    try:
        if fname_lower.endswith(".csv"):
            df_map = {"Sheet1": pd.read_csv(io.BytesIO(file_bytes))}
        else:
            xls = pd.ExcelFile(io.BytesIO(file_bytes))
            df_map = {sheet: xls.parse(sheet) for sheet in xls.sheet_names}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse {filename}: {str(e)}")

    text_parts = []
    for sheet_name, df in df_map.items():
        df = df.dropna(how="all").fillna("")
        text_parts.append(f"[Sheet: {sheet_name}]\n{df.to_string(index=False)}")

    full_text = "\n\n".join(text_parts)

    if not full_text.strip():
        raise HTTPException(status_code=422, detail=f"{filename} appears to be empty.")

    return {
        "filename":   filename,
        "full_text":  full_text,
        "page_count": len(df_map),
    }
