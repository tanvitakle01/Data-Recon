# TODO - SAP reconciliation fixes

- [x] 1) Remove duplicate UI (radio group / Step 1) from `frontend/src/pages/ReconciliationPage.jsx` so only `UploadSection` renders it.

- [x] 2) Make SAP preview/table use the required `/api/s4/test-preview` contract and show first 10 rows with required headers/fields.

- [x] 3) Refactor `frontend/src/components/SAPFetchSection.jsx` to remove hardcoded localhost URLs and use existing API service layer.

- [ ] 4) Update `backend/routes/s4_test_preview.py` to return `data[]` with keys: `SalesOrder`, `SalesOrderType`, `SoldToParty`, `RequestedDeliveryDate`, `TotalNetAmount`.
- [x] 5) Pass fetched SAP preview rows into reconciliation when SAP mode is selected.

- [x] 6) Update `backend/routes/reconcile.py` to use provided `source_rows` in sap_mode (instead of connector.fetch()) so reconciliation uses the preview rows.

- [x] 7) Keep Excel mode behavior unchanged.

- [x] 8) Remove unused `S4Preview` import from `frontend/src/App.jsx`; optionally delete the unused component if safe.

- [ ] 9) Manual acceptance: verify “Load Sales Orders” shows success + rows=10 + correct table; Run Reconciliation works using fetched SAP source data.

