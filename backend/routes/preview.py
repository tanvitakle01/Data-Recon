from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, Form

from backend.excel_comparator.core.loader import load_tabular_detailed



# Returns workbook sheet list + selected sheet dataframe preview (CSV or Excel)


router = APIRouter()

# Default preview size (unchanged — the wizard's own upload-preview cards
# render this many rows). A caller that needs a properly-sized, REPRESENTATIVE
# sample of the real file — e.g. Gate 2 sample replay, which needs enough rows
# that a selective filter/business rule has a realistic chance of matching
# something (5 rows of an 83,000-row extract filtered to ~0.2% of rows will
# almost always come back empty by pure bad luck, not a pipeline defect) —
# passes a larger `rows` explicitly; nothing about which rows a specific
# contract's rule would match is assumed or hardcoded here, only the sample
# SIZE differs.
_DEFAULT_PREVIEW_ROWS = 5
_MAX_PREVIEW_ROWS = 1000


@router.post("/preview")
async def preview_excel(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(default=None),
    rows: int = Form(default=_DEFAULT_PREVIEW_ROWS),
):
    filename_l = (file.filename or "").lower()
    if not (filename_l.endswith(".xlsx") or filename_l.endswith(".xls") or filename_l.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload .xlsx, .xls, or .csv")

    content = await file.read()

    # Load workbook and pick active sheet (same logic as Streamlit)
    initial = load_tabular_detailed(content, file.filename or "", sheet_name=None)
    sheets = initial.get("sheets") or []

    active_sheet = initial.get("active_sheet")
    if sheet_name and sheet_name in sheets:
        active_sheet = sheet_name
    elif not active_sheet and sheets:
        active_sheet = sheets[0]

    # Load selected sheet
    loaded = load_tabular_detailed(content, file.filename or "", sheet_name=active_sheet)

    df = loaded["df"]
    row_cap = max(1, min(int(rows), _MAX_PREVIEW_ROWS))

    return {
        "filename": file.filename,
        "sheets": sheets,
        "active_sheet": active_sheet,
        "rows": loaded["row_count"],
        "cols": loaded["col_count"],
        "columns": df.columns.tolist(),
        "preview": df.head(row_cap).astype(str).to_dict(orient="records"),
    }


