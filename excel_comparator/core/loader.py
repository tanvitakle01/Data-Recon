from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

def _materialize_file(file_obj: Any) -> Any:
    if file_obj is None:
        raise ValueError("No file provided.")

    if isinstance(file_obj, (str, bytes, bytearray)):
        return file_obj

    if hasattr(file_obj, "getvalue"):
        data = file_obj.getvalue()
        if not data:
            raise ValueError("Uploaded file is empty or unreadable.")
        return BytesIO(data)

    if hasattr(file_obj, "read"):
        data = file_obj.read()
        if not data:
            raise ValueError("Uploaded file is empty or unreadable.")
        return BytesIO(data)

    raise ValueError("Unsupported file object type.")


def load_excel(file_obj: Any, sheet_name: str | None = None) -> dict[str, Any]:
    """
    Returns:
        {
            "df": pd.DataFrame,
            "sheets": List[str],
            "active_sheet": str,
            "row_count": int,
            "col_count": int
        }
    """
    stream = _materialize_file(file_obj)

    try:
        excel_file = pd.ExcelFile(stream)
    except Exception as exc:
        raise ValueError("Unable to read Excel file. Please verify the file format.") from exc

    sheets = excel_file.sheet_names or []
    if not sheets:
        raise ValueError("No worksheets found in the uploaded file.")

    active_sheet = sheet_name or sheets[0]
    if active_sheet not in sheets:
        raise ValueError(f"Selected sheet '{active_sheet}' does not exist.")

    try:
        df = pd.read_excel(excel_file, sheet_name=active_sheet, dtype=object)
    except Exception as exc:
        raise ValueError(f"Failed to load sheet '{active_sheet}'.") from exc

    df.columns = [str(col).strip() for col in df.columns]

    if df.empty:
        raise ValueError("File appears to be empty.")

    return {
        "df": df,
        "sheets": sheets,
        "active_sheet": active_sheet,
        "row_count": int(df.shape[0]),
        "col_count": int(df.shape[1]),
    }
