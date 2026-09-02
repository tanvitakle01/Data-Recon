from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Response, UploadFile
from fastapi.responses import PlainTextResponse

from backend.recon_engine.insights import builder as insights_builder
from backend.recon_engine.insights.normalize import UnrecognizedWorkbookError

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_or_upload_id(body: dict[str, Any]) -> tuple[str | None, str | None]:
    run_id = body.get("run_id")
    upload_id = body.get("upload_id")
    if not run_id and not upload_id:
        raise HTTPException(status_code=400, detail="Missing run_id or upload_id")
    return (str(run_id) if run_id else None), (str(upload_id) if upload_id else None)


@router.post("/insights/from-run-id")
async def generate_insights_from_run_id(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Generate insights for a persisted V2 reconciliation run.
    Expects: { "run_id": "<id from POST /api/recon/runs>" }"""
    run_id = body.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id")

    try:
        payload = insights_builder.build_for_run(str(run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights for run: {exc}")

    return {"success": True, "payload": payload}


@router.post("/insights/upload")
async def generate_insights_from_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Generate insights from an uploaded reconciliation results workbook —
    the same Summary/All Records/Mapping Details .xlsx a completed run's
    "Download comparison workbook" produces. Any other shape is rejected with
    a clear message rather than guessed at."""
    filename_l = (file.filename or "").lower()
    if not (filename_l.endswith(".xlsx") or filename_l.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload the .xlsx results workbook.")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        payload = insights_builder.build_for_upload(content)
    except UnrecognizedWorkbookError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights for upload: {exc}")

    return {"success": True, "payload": payload}


@router.post("/insights/pdf")
async def download_insights_pdf(body: dict[str, Any] = Body(...)) -> Response:
    """Structured PDF export of a run's or an uploaded workbook's insights —
    same facts payload the other two endpoints return, rendered as a
    printable report (see ``insights/pdf.py``). Used by the Insights page's
    "Download PDF" button and the chat assistant's "View Insights" pill/text
    intent alike."""
    run_id, upload_id = _run_or_upload_id(body)
    try:
        pdf_bytes = insights_builder.pdf_for(run_id=run_id, upload_id=upload_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights PDF: {exc}")

    name = run_id or upload_id
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="insights_{name}.pdf"'},
    )


@router.post("/insights/records")
async def query_insights_records(body: dict[str, Any] = Body(...)) -> Any:
    """Drill-through: given the ``filter`` spec a facts payload handed back
    verbatim, return the matching subset of records — sort, page, and CSV
    export.
    Expects: { "run_id"|"upload_id": str, "filter": {...}, "sort"?, "sortDir"?,
               "page"?, "pageSize"?, "format"?: "json"|"csv" }"""
    run_id, upload_id = _run_or_upload_id(body)
    filter_spec = body.get("filter") or {}
    fmt = str(body.get("format") or "json").lower()

    try:
        if fmt == "csv":
            csv_text = insights_builder.records_csv_for(run_id=run_id, upload_id=upload_id, filter_spec=filter_spec)
            name = run_id or upload_id
            return PlainTextResponse(
                content=csv_text,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="insights_records_{name}.csv"'},
            )

        result = insights_builder.records_for(
            run_id=run_id,
            upload_id=upload_id,
            filter_spec=filter_spec,
            sort=body.get("sort"),
            sort_dir=str(body.get("sortDir") or "asc"),
            page=int(body.get("page") or 1),
            page_size=int(body.get("pageSize") or 100),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to query records: {exc}")

    return {"success": True, **result}
