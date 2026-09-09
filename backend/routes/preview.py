from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, Form

from backend.excel_comparator.core.loader import load_tabular_detailed



# Returns workbook sheet list + selected sheet dataframe preview (CSV or Excel)


router = APIRouter()


@router.post("/preview")
async def preview_excel(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(default=None),
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

    return {
        "filename": file.filename,
        "sheets": sheets,
        "active_sheet": active_sheet,
        "rows": loaded["row_count"],
        "cols": loaded["col_count"],
        "columns": df.columns.tolist(),
        "preview": df.head(5).astype(str).to_dict(orient="records"),
    }


