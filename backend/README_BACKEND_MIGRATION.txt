Backend migration quick-start (FastAPI + production-style architecture)

1) What was migrated
- Kept the existing reconciliation “core” logic:
  - backend/excel_comparator/core/*
  - backend/excel_comparator/utils/helpers.py (summary + remark classification)
- Added a production-style FastAPI API layer:
  - backend/routes/* (APIRouter endpoints)
  - backend/services/* (service-layer wrappers)
  - backend/models/schemas.py (Pydantic request/response shapes)

2) Directory layout (new)
backend/
  main.py
  models/
    schemas.py
  routes/
    preview.py     -> POST /preview
    mapping.py     -> POST /auto-map
    reconcile.py   -> POST /reconcile
    (upload.py remains from earlier prototype)
  services/
    excel_service.py         (helpers for reading uploads + record/frame conversions)
    mapping_service.py       (wraps auto_map_columns)
    reconciliation_service.py (runs reconciliation + builds summary/records)

3) Running the backend
- Create/activate your venv (if applicable).
- Install dependencies from requirements.txt at repo root.
- Start server:
  uvicorn backend.main:app --host 127.0.0.1 --port 8000

4) CORS
- backend/main.py configures CORS for:
  http://localhost:5173

5) API endpoints

A) POST /preview
Purpose: preview an uploaded Excel file.
Consumes:
- multipart/form-data
  - file: UploadFile (.xlsx / .xls)

Returns JSON:
{
  "filename": "<original name>",
  "rows": <int>,
  "cols": <int>,
  "columns": ["col1","col2",...],
  "preview": [ {"col1": v1, "col2": v2, ...}, ... ]  // first 5 rows
}

Implementation:
- backend/routes/preview.py
- backend/services/excel_service.py

B) POST /auto-map
Purpose: auto-detect mappings between source and target columns.
Consumes (JSON):
{
  "source_columns": ["..."],
  "target_columns": ["..."]
}

Returns JSON:
{
  "mappings": [
    { "source": "<source col>", "target": "<target col>", "score": <float> }
  ],
  "mapping": {
    "key_fields": [ {"source_col": "...", "target_col": "..."}, ...],
    "compare_fields": [ {"source_col": "...", "target_col": "..."}, ...],
    "options": {"case_insensitive": true, "trim_whitespace": true}
  }
}

Notes:
- The underlying mapping is produced by backend/excel_comparator/core/auto_mapper.py
  (difflib + keyword classification). RapidFuzz is not required in this repo’s current logic.
- The route synthesizes a score because the underlying core mapping does not output one.

Implementation:
- backend/routes/mapping.py
- backend/services/mapping_service.py

C) POST /reconcile
Purpose: execute reconciliation scenarios 1..4 and return record-level results.
Consumes (JSON):
{
  "source_data": [ {"colA": "...", "colB": 123, ...}, ... ],
  "target_data": [ {"colX": "...", ...}, ... ],
  "mapping": { /* mapping returned by /auto-map */ }
}

Returns JSON:
{
  "summary": {
    "total_records": <int>,
    "matched": <int>,
    "unmatched": <int>,
    "match_percentage": <float>,
    "qty_mismatch": <int>,
    "missing_in_target": <int>,
    "extra_in_target": <int>
  },
  "matched_records": [ { ...row fields..., "Remarks": "..."? }, ... ],
  "unmatched_records": [ { ...row fields..., "Remarks": "..."? }, ... ]
}

Notes:
- The core comparator lives in backend/excel_comparator/core/comparator.py
- It produces a “Remarks” column with scenario messages.
- backend/services/reconciliation_service.py classifies remarks into matched/unmatched.
- Per your requirement, this endpoint returns ONLY reconciliation results (no AI text).

Implementation:
- backend/routes/reconcile.py
- backend/services/reconciliation_service.py

6) Downloadable annotated Excel
Current status:
- The repo contains write_annotated_excel(...) in backend/excel_comparator/core/writer.py.
- The /reconcile endpoint currently does not return the annotated Excel bytes.

Recommended approach for frontend:
- Add a dedicated endpoint (later) like:
  POST /reconcile/annotated
  that returns application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
  or returns base64.

If you want, I can implement that download endpoint next.

7) Example payloads

A) /preview
Request (multipart):
- file=<your.xlsx>

Response (example):
{
  "filename": "S4_Source_Test.xlsx",
  "rows": 100,
  "cols": 10,
  "columns": ["Plant", "Material", "Qty"],
  "preview": [ {"Plant":"p1","Material":"m1","Qty":"10"}, ... ]
}

B) /auto-map
{
  "source_columns": ["Plant", "Material", "Qty"],
  "target_columns": ["Plant_ID", "Material_ID", "Quantity"]
}

C) /reconcile
{
  "source_data": [
    {"Plant":"P1","Material":"M1","Qty":"10"},
    {"Plant":"P2","Material":"M2","Qty":"20"}
  ],
  "target_data": [
    {"Plant_ID":"P1","Material_ID":"M1","Quantity":"10"},
    {"Plant_ID":"P2","Material_ID":"M2","Quantity":"18"}
  ],
  "mapping": {
    "key_fields": [
      {"source_col":"Plant","target_col":"Plant_ID"},
      {"source_col":"Material","target_col":"Material_ID"}
    ],
    "compare_fields": [
      {"source_col":"Qty","target_col":"Quantity"}
    ],
    "options": {"case_insensitive": true, "trim_whitespace": true}
  }
}

8) What to do next (frontend)
- Implement React components to:
  1) Upload source + target
  2) Show previews
  3) Call /auto-map with detected columns
  4) Render ColumnMappingTable
  5) On Run, call /reconcile with full source/target records + mapping
  6) Render SummaryCards + matched/unmatched tables
  7) Add error/loading states

End of file.

