from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Request

from backend.API_conn.services.reconcilation_service import ReconciliationService

from backend.excel_comparator.core.auto_mapper import auto_map_columns
from backend.excel_comparator.core.comparator import ExcelComparator
from backend.excel_comparator.core.loader import load_excel
from backend.excel_comparator.core.mapper import ColumnMapper

router = APIRouter()



def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.fillna("").to_dict(orient="records")


@router.post("/reconcile")
async def reconcile_route(
    request: Request,

    # Excel mode inputs

    source_file: Optional[UploadFile] = File(default=None),
    target_file: Optional[UploadFile] = File(default=None),

    # SAP mode inputs
    source_mode: Optional[str] = Form(default=None),
    target_mode: Optional[str] = Form(default=None),

    # Optional SAP preview rows (JSON string) provided by frontend
    source_rows: Optional[str] = Form(default=None),

    # Optional sheet selection for Excel
    sheet_name_source: Optional[str] = Form(default=None),
    sheet_name_target: Optional[str] = Form(default=None),
):

    """Reconcile two datasets and return exactly the core comparator output.

    TEMP DEBUG (stale-code check): if this route is hit, this code is executing.

    Requirements:

    - Must reuse exact reconciliation workflow:
      mapping = auto_map_columns(source_df, target_df)
      mapper = ColumnMapper(mapping)
      mapper.validate(source_df, target_df)
      comparator = ExcelComparator(source_df, target_df, mapper)
      result_df, summary = comparator.run(scenarios=[1,2,3,4])
    """


    try:
        # Decide mode


        excel_mode = source_mode is None and target_mode is None
        sap_mode = (source_mode == "sap" and target_mode == "sap")

        if not excel_mode and not sap_mode:
            raise HTTPException(
                status_code=400,
                detail="Provide either (source_file+target_file) OR (source_mode=sap and target_mode=sap).",
            )

        if excel_mode:
            if source_file is None or target_file is None:
                raise HTTPException(status_code=400, detail="source_file and target_file are required for Excel mode.")

            # load files using load_excel()
            source_bytes = await source_file.read()
            target_bytes = await target_file.read()
            source_loaded = load_excel(BytesIO(source_bytes), sheet_name=sheet_name_source)
            target_loaded = load_excel(BytesIO(target_bytes), sheet_name=sheet_name_target)

            source_df: pd.DataFrame = source_loaded["df"]
            target_df: pd.DataFrame = target_loaded["df"]

        else:
            # SAP mode: source comes from either provided preview rows OR connector fetch.
            service = ReconciliationService()

            # If frontend provides `source_rows` (JSON string), use it as the source dataset.
            source_df: pd.DataFrame
            if source_rows:
                try:
                    import json

                    parsed = json.loads(source_rows)
                    source_df = pd.DataFrame(parsed)
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"Invalid source_rows JSON: {exc}")
            else:
                source_df = service.get_source_data()

            # Target is still fetched from IBP connector for SAP mode.
            target_df = service.get_target_data()



        # EXACT workflow
        # TEMP DEBUG: verify sheet loading
        print("===== SOURCE COLUMNS =====")
        print(source_df.columns.tolist())
        print("===== TARGET COLUMNS =====")
        print(target_df.columns.tolist())
        print("===== SOURCE SHAPE =====")
        print(source_df.shape)
        print("===== TARGET SHAPE =====")
        print(target_df.shape)

        mapping_result = auto_map_columns(source_df, target_df)

        mapper = ColumnMapper(mapping_result["mapping"])



        # TEMP DEBUG: inspect mapper parsed fields (immediately before validate)
        print("===== COLUMN MAPPER =====")
        print("len(mapper.key_fields)=", len(mapper.key_fields))
        print("len(mapper.compare_fields)=", len(mapper.compare_fields))


        mapper.validate(source_df, target_df)
        comparator = ExcelComparator(source_df, target_df, mapper)
        result_df, summary = comparator.run(scenarios=[1, 2, 3, 4])




        return {
            "summary": summary,
            "mapping": mapping,
            "columns": result_df.columns.tolist(),
            "results": _df_to_records(result_df),
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {exc}")

