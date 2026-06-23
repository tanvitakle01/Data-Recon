from fastapi import APIRouter, UploadFile, File
import pandas as pd
from io import BytesIO

router = APIRouter()


@router.post("/preview")
async def preview_excel(file: UploadFile = File(...)):

    content = await file.read()

    df = pd.read_excel(BytesIO(content))

    return {
        "filename": file.filename,
        "rows": len(df),
        "cols": len(df.columns),
        "columns": df.columns.tolist(),
        "preview": df.head(5).astype(str).to_dict(orient="records")
    }