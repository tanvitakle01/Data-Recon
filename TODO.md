# TODO_PHASE2 - Data Reconciliation (Insights Stability)

- [ ] Fix runtime crash: define/derive `topRisks` in `OperationalIntelligencePanel` (was referenced but not defined).
- [ ] Fix missing React imports/hooks: ensure `useMemo`, `useState`, `useEffect`, `useRef` are imported in `InsightsPage.jsx`.
- [x] Fix ResponsiveContainer warnings: ensure chart wrappers always have explicit non-zero heights and stable parents.

- [ ] Prevent charts from rendering when payload/charts data is empty; optionally render skeleton/no-data blocks.
- [ ] Add a small error boundary wrapper for InsightsPage content to isolate component failures.
- [ ] Remove unused constants (e.g. `COLORS`) or integrate them cleanly.
- [ ] Ensure layout stability for charts inside flex/grid containers.
- [ ] Run frontend build/lint (or at least `npm test`/`npm run build`) and verify no console runtime errors.

