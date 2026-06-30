# TODO_PHASE2.md

## Reconciliation Analytics – Operational Exception Intelligence Upgrade

### Step 1: Fix Recommendations duplication
- Update `frontend/src/components/insights/OperationalIntelligenceCenter.jsx`
  - Stop using `aiInsights.slice(0, 5)` for Recommendations.
  - Prefer a dedicated recommendation field from backend payload.
  - If absent, derive distinct actions from operationalIntelligence structure (patterns/exceptions/trends/risk) without copying AI insight strings.

### Step 2: Make AI Insights actionable (data-backed)
- Update `frontend/src/components/insights/OperationalIntelligenceCenter.jsx`
  - Convert AI insight strings into more factual findings when numbers exist.
  - If backend payload already supplies actionable sentences, render as-is; otherwise format using available structured fields.

### Step 3: Remove generic executive phrasing in ExecutiveSummaryCard
- Update `frontend/src/components/insights/ExecutiveSummaryCard.jsx`
  - Replace “Operational Health Score” / “Business Impact” with reconciliation exception counts.
  - Remove placeholder business-impact bullets that are not sourced from computed data.

### Step 4: ParetoAnalysis genuine ranked view + cumulative coverage
- Update `frontend/src/components/insights/ParetoAnalysisCard.jsx`
  - Show top contributors with ranked entities and percent/share.
  - Show cumulative coverage using `coverage80Percent` or equivalent backend value.
  - Hide blocks (no empty-noise cards) when data is missing.
  - Extend to Customers/Regions if available; otherwise hide.

### Step 5: Risk Analysis add “why this entity is risky”
- Update `frontend/src/components/insights/RiskEntitiesCard.jsx`
  - Add “Why this entity is risky” using contributing factors/drivers/factors.
  - Use ranked list and show percent-of-failures if provided.

### Step 6: Trend Analysis upgrade narrative
- Update `frontend/src/components/insights/TrendIntelligenceCard.jsx`
  - Replace generic direction labeling with: from/to, volume numbers, change%, and factual interpretation.

### Step 7: Tighten empty-noise rendering rules
- Update the insight section components to hide cards when their dataset is empty.
  - Prefer compact placeholders: “No supplier-level patterns detected” instead of large empty bordered cards.

### Step 8: Ensure section headings remain exactly as required
- Verify all headings match:
  - Accuracy, Total Mismatches, Missing Records, Extra Records
  - AI Insights, Operational Intelligence, Pareto Analysis, Risk Analysis, Trend Analysis

### Step 9: Build/test
- Run frontend checks:
  - `cd frontend && npm run lint`
  - `cd frontend && npm run build`

