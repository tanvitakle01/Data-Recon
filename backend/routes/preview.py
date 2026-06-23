from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, File, UploadFile, Form

from backend.excel_comparator.core.loader import load_excel



# Returns workbook sheet list + selected sheet dataframe preview


router = APIRouter()


@router.post("/preview")
async def preview_excel(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(default=None),
):
    content = await file.read()

    # Load workbook and pick active sheet (same logic as Streamlit)
    initial = load_excel(BytesIO(content), sheet_name=None)
    sheets = initial.get("sheets") or []

    active_sheet = initial.get("active_sheet")
    if sheet_name and sheet_name in sheets:
        active_sheet = sheet_name
    elif not active_sheet and sheets:
        active_sheet = sheets[0]

    # Load selected sheet
    loaded = load_excel(BytesIO(content), sheet_name=active_sheet)

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


