# Frontend (React + Vite)

UI for **Data Reconciliation**.

It lets you:
1. Upload a **Source** Excel file and a **Target** Excel file
2. Preview the first 5 rows from each file
3. Auto-map columns (reconciliation key fields vs quantity/compare fields)
4. Run reconciliation and view matched/unmatched results + summary metrics

---

## Tech stack

- React (via Vite)
- axios for HTTP calls
- UI is composed from `src/components/*`

Backend base URL (hard-coded):
- `http://localhost:8000`

---

## Project structure (high level)

- `src/App.jsx` – entry component
- `src/pages/ReconciliationPage.jsx` – page layout
- `src/components/UploadSection.jsx` – main flow (upload → map → reconcile → results)
- `src/components/FileUploadCard.jsx` – uploads files and calls `/preview`
- `src/components/ColumnMappingTable.jsx` – shows detected mappings
- `src/components/SummaryCards.jsx` – shows summary metrics
- `src/components/ReconciliationResults.jsx` – shows matched/unmatched records tables
- `src/services/api.js` – axios client (`baseURL: http://localhost:8000`)

---

## How the reconciliation flow works

All flow logic is implemented in:
- `src/components/UploadSection.jsx`

### 1) Upload + preview
When you upload each Excel file, the frontend calls:
- **POST** `/preview`

Backend response shape (what the UI expects):
```json
{
  "filename": "...",
  "rows": 123,
  "cols": 10,
  "columns": ["ColA", "ColB", ...],
  "preview": [ {"ColA": "...", "ColB": "..."}, ... ]
}
```

The UI uses:
- `columns` to decide when reconciliation can run
- `preview` as the dataset sent to `/reconcile` (currently a **subset**)

### Important: Preview limitation (affects results)
The frontend sends only:
- `sourcePreview.preview` and `targetPreview.preview`

The backend `/preview` returns:
- `df.head(5)` (first **5 rows**)

So reconciliation is executed on a **5-row subset**, not the full dataset. If reconciliation results look “off”, this is a common cause.

### 2) Auto-map columns
After both previews are loaded, the frontend calls:
- **POST** `/auto-map`

Request body:
```json
{
  "source_columns": ["..."],
  "target_columns": ["..."]
}
```

Backend mapping logic:
- `backend/services/mapping_service.py` builds DataFrames from just the column headers
- `backend/excel_comparator/core/auto_mapper.py` auto-detects logical column roles using:
  - keyword classification (location/product/period/quantity)
  - fuzzy matching (difflib) for remaining columns
  - positional fallback
  - a numeric-type inference step to promote one likely quantity pair

Backend returns:
- `mappings`: display rows for the UI
- `mapping`: the actual config used by `/reconcile`

### 3) Reconcile
Then the frontend calls:
- **POST** `/reconcile`

Request body:
```json
{
  "source_data": [ {"col": "value"}, ... ],
  "target_data": [ {"col": "value"}, ... ],
  "mapping": { "key_fields": [...], "compare_fields": [...], "options": {...} }
}
```

Backend reconciliation logic:
- `backend/services/reconciliation_service.py`
  - Builds match keys from `key_fields`
  - Compares mapped `compare_fields` (quantity) for mismatches
  - Creates a `Remarks` column in the annotated target output
  - Derives `Scenario` as:
    - `MATCHED`
    - other scenarios (mismatches, missing, extras)

Frontend expects the response:
```json
{
  "summary": {
    "total_records": 5,
    "matched": 2,
    "unmatched": 3,
    "match_percentage": 40.0,
    "qty_mismatch": 1,
    "missing_in_target": 2,
    "extra_in_target": 0
  },
  "matched_records": [ ... ],
  "unmatched_records": [ ... ]
}
```

---

## Running locally

### Prerequisites
- Node.js + npm
- Backend running at `http://localhost:8000`

### Install
From `frontend/`:
```bash
npm install
```

### Dev server
```bash
npm run dev
```

### Build
```bash
npm run build
```

### Lint
```bash
npm run lint
```

---

## Configuration notes

- The backend URL is currently hard-coded in `src/services/api.js`.
  - If your backend runs on a different host/port, update:
    - `frontend/src/services/api.js`

---

## Troubleshooting (reconciliation results not as expected)

1. **Verify you’re reconciling the full files**
   - Current UI behavior reconciles only the first 5 preview rows.
   - If you need full reconciliation, you must add/modify a backend endpoint to fetch full rows and update the frontend to send full datasets.

2. **Confirm column mapping roles**
   - Auto-mapping uses keyword + fuzzy heuristics.
   - If column names differ significantly from expected patterns, key/compare fields may be wrong.

3. **Check for quantity mismatches vs exact equality**
   - Quantity mismatch logic converts values with `pd.to_numeric(...)`.
   - Mismatch is flagged when numeric values differ.

4. **Ensure key columns exist and are consistent**
   - Keys are built by normalizing values from `key_fields`.
   - If key detection is wrong, records can be classified as missing/extra.

---

## API endpoints used by the frontend

- `POST /preview` – upload Excel, return column list + first 5 rows preview
- `POST /auto-map` – auto-detect mappings between source/target columns
- `POST /reconcile` – run reconciliation on the provided (currently preview) rows

