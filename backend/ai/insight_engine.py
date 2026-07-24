import pandas as pd

from backend.ai.insight_adapter import CockpitAdapter


class InsightEngine:
    """ 
    Generates business-friendly, dashboard-ready reconciliation insights.

    Output JSON shape (Phase 1 + Phase 2):

    Phase 1 (executive):
    {
      "summary": {...},
      "executiveSummary": {"text": "..."},
      "risk": {"score": 0, "category": "Low", "drivers": [...]},
      "rootCauses": [...],
      "businessImpacts": [...],
      "recommendations": [...],
      "kpis": [...],
      "insights": [...],
      "charts": {...}
    }

    Phase 2 (operational + analytics):
    {
      "operationalIntelligence": {...},
      "dimensionInsights": [...],
      "recurringIssues": [...],
      "topRiskEntities": {...},
      "criticalExceptions": [...],
      "patterns": [...],
      "comparisons": [...],
      "trendInsights": [...],
      "paretoAnalysis": {...}
    }
    """

    # ----------------------------
    # Public API
    # ----------------------------
    def generate(self, df: pd.DataFrame) -> dict:
        if df is None or df.empty:
            return self._empty_payload()

        df = df.copy()

        remarks = self._get_remarks_series(df)
        if remarks is None:
            return self._empty_payload()

        mismatch_mask = self._is_any_mismatch(remarks)
        mismatches = df.loc[mismatch_mask].copy()

        total_records = int(len(df))
        mismatched_records = int(len(mismatches))
        matched_records = max(0, total_records - mismatched_records)

        accuracy = (matched_records / total_records * 100.0) if total_records else 0.0

        # counts by mismatch type (must be aligned to `mismatches`)
        if "Remarks" in mismatches.columns:
            mismatch_remarks = mismatches["Remarks"]
            type_counts = self._count_by_type(remarks_series=mismatch_remarks)
        else:
            type_counts = {
                "Missing in Target": 0,
                "Extra in Target": 0,
                "Quantity Mismatch": 0,
            }

        missing_in_target = int(type_counts.get("Missing in Target", 0))
        extra_in_target = int(type_counts.get("Extra in Target", 0))
        qty_mismatch = int(type_counts.get("Quantity Mismatch", 0))

        dominant = self._dominant_category(missing_in_target, extra_in_target, qty_mismatch)
        severity = self._severity_rating(accuracy, mismatched_records)

        summary = {
            "totalRecords": total_records,
            "matchedRecords": matched_records,
            "mismatchedRecords": mismatched_records,
            "accuracy": round(float(accuracy), 1),
            "dominantMismatchCategory": dominant,
            "severity": severity,
        }

        # mismatch breakdown with percentages
        kpis = self._build_kpis(
            total_records=total_records,
            missing_in_target=missing_in_target,
            extra_in_target=extra_in_target,
            qty_mismatch=qty_mismatch,
        )

        # Compute additional execution intelligence (phase 1)
        affected_plants = self._extract_top_dimension_values(
            mismatches,
            ["plant", "werks", "location", "storagelocation"],
            max_items=10,
        )
        affected_materials = self._extract_top_dimension_values(
            mismatches,
            ["material", "matnr", "product", "item", "sku"],
            max_items=10,
        )

        executive_summary = self._generate_executive_summary(
            accuracy=summary["accuracy"],
            mismatched_records=mismatched_records,
            dominant_mismatch_category=dominant,
            severity=severity,
            affected_plants=affected_plants,
            affected_materials=affected_materials,
        )

        mismatch_count = mismatched_records
        mismatch_percentage = (mismatched_records / total_records * 100.0) if total_records else 0.0

        trend_growth = self._estimate_trend_growth(df, mismatches)
        risk = self._generate_risk_score(
            accuracy=summary["accuracy"],
            mismatch_count=mismatch_count,
            affected_plants=affected_plants,
            affected_materials=affected_materials,
            trend_growth=trend_growth,
            mismatch_percentage=mismatch_percentage,
        )

        root_causes = self._generate_root_causes(
            missing_in_target=missing_in_target,
            extra_in_target=extra_in_target,
            qty_mismatch=qty_mismatch,
            mismatches=mismatches,
        )

        business_impacts = self._generate_business_impacts(
            root_causes=root_causes,
            missing_in_target=missing_in_target,
            extra_in_target=extra_in_target,
            qty_mismatch=qty_mismatch,
        )

        recommendations = self._generate_recommendations(root_causes=root_causes, risk=risk, severity=severity)

        # Preserve existing dashboard insights + charts
        insights: list[str] = []

        if executive_summary and isinstance(executive_summary, dict) and executive_summary.get("text"):
            insights.append(executive_summary["text"])

        insights.extend(
            self._risk_based_insights(
                missing_in_target=missing_in_target,
                extra_in_target=extra_in_target,
                qty_mismatch=qty_mismatch,
                severity=severity,
            )
        )

        root_insights = self._root_cause_insights(mismatches)
        insights.extend(root_insights)

        trend_insight, trend_points = self._trend_detection(df, mismatches)
        if trend_insight:
            insights.append(trend_insight)

        charts = self._build_charts(mismatches, type_counts, trend_points=trend_points)

        # Phase 2 (operational intelligence)
        operational_payload = self._build_operational_intelligence(mismatches=mismatches, full_df=df)

        payload = {
            "summary": summary,
            "executiveSummary": executive_summary,
            "risk": risk,
            "rootCauses": root_causes,
            "businessImpacts": business_impacts,
            "recommendations": recommendations,
            "kpis": kpis,
            "insights": self._dedupe_insights([i for i in insights if i]),
            "charts": charts,
            # Phase 2 keys
            "operationalIntelligence": operational_payload.get("operationalIntelligence", {}),
            "dimensionInsights": operational_payload.get("dimensionInsights", []),
            "recurringIssues": operational_payload.get("recurringIssues", []),
            "topRiskEntities": operational_payload.get("topRiskEntities", {}),
            "criticalExceptions": operational_payload.get("criticalExceptions", []),
            "patterns": operational_payload.get("patterns", []),
            "comparisons": operational_payload.get("comparisons", []),
            "trendInsights": operational_payload.get("trendInsights", []),
            "paretoAnalysis": operational_payload.get("paretoAnalysis", {}),
        }

        # Phase 3 (Enterprise Reconciliation Intelligence Center) — purely additive,
        # reshapes the payload above; existing consumers are unaffected.
        payload["cockpit"] = CockpitAdapter(self).build(
            payload=payload, df=df, mismatches=mismatches, type_counts=type_counts
        )

        return payload

    # ----------------------------
    # Column detection helpers
    # ----------------------------
    def _detect_column(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        if df is None or df.empty:
            return None
        cols = list(df.columns)
        if not cols:
            return None

        norm_map = {c: self._normalize_col(c) for c in cols}
        wanted = [self._normalize_col(x) for x in candidates]

        for c, n in norm_map.items():
            for w in wanted:
                if w in n:
                    return c
        return None

    def _normalize_col(self, s: str) -> str:
        return str(s).strip().lower().replace(" ", "").replace("_", "")

    # ----------------------------
    # Remarks + mismatch parsing
    # ----------------------------
    def _get_remarks_series(self, df: pd.DataFrame) -> pd.Series | None:
        if "Remarks" not in df.columns:
            return None
        return df["Remarks"].fillna("").astype(str)

    def _is_any_mismatch(self, remarks: pd.Series) -> pd.Series:
        return remarks.str.contains(
            r"MISSING IN TARGET|EXTRA IN TARGET|QTY MISMATCH",
            case=False,
            regex=True,
            na=False,
        )

    def _count_by_type(self, remarks_series: pd.Series) -> dict:
        remarks_series = remarks_series.fillna("").astype(str)

        def count(pattern: str) -> int:
            return int(remarks_series.str.contains(pattern, case=False, na=False).sum())

        missing = count(r"MISSING IN TARGET")
        extra = count(r"EXTRA IN TARGET")
        qty = count(r"QTY MISMATCH")

        return {
            "Missing in Target": missing,
            "Extra in Target": extra,
            "Quantity Mismatch": qty,
        }

    # ----------------------------
    # Executive/severity helpers
    # ----------------------------
    def _dominant_category(self, missing: int, extra: int, qty: int) -> str:
        if missing >= extra and missing >= qty and missing > 0:
            return "Missing in Target"
        if extra >= missing and extra >= qty and extra > 0:
            return "Extra in Target"
        if qty > 0:
            return "Quantity Mismatch"
        return "No mismatches"

    def _severity_rating(self, accuracy: float, mismatched_records: int) -> str:
        if mismatched_records <= 0:
            return "Low"
        if accuracy >= 95.0 and mismatched_records <= 50:
            return "Low"
        if accuracy >= 90.0:
            return "Medium"
        return "High"

    def _build_kpis(self, total_records: int, missing_in_target: int, extra_in_target: int, qty_mismatch: int) -> list[dict]:
        def pct(n: int) -> float:
            return round((n / total_records * 100.0), 1) if total_records else 0.0

        return [
            {"title": "Missing in Target", "value": missing_in_target, "percentage": pct(missing_in_target)},
            {"title": "Extra in Target", "value": extra_in_target, "percentage": pct(extra_in_target)},
            {"title": "Quantity Mismatch", "value": qty_mismatch, "percentage": pct(qty_mismatch)},
        ]

    # ----------------------------
    # Root cause insights
    # ----------------------------
    def _root_cause_insights(self, mismatches: pd.DataFrame) -> list[str]:
        insights: list[str] = []

        if mismatches is None or mismatches.empty:
            return insights

        plant_col = self._detect_column(mismatches, ["plant", "werks", "location", "storagelocation"])
        material_col = self._detect_column(mismatches, ["material", "matnr", "product", "item", "sku"])
        delivery_col = self._detect_column(mismatches, ["deliverydate", "delivery date", "postingdate", "documentdate", "date", "reqdeliverydate"])
        bu_col = self._detect_column(mismatches, ["businessunit", "business unit", "division", "bukrs", "orgunit", "org unit"])

        if material_col:
            top = mismatches[material_col].fillna("Unknown").astype(str).value_counts().head(5)
            if not top.empty:
                mat = str(top.index[0])
                share = round(float(top.iloc[0] / max(1, len(mismatches)) * 100.0), 1)
                insights.append(f"Material {mat} contributes to {share}% of all reconciliation exceptions.")

        if plant_col:
            top = mismatches[plant_col].fillna("Unknown").astype(str).value_counts().head(5)
            if not top.empty:
                pl = str(top.index[0])
                share = round(float(top.iloc[0] / max(1, len(mismatches)) * 100.0), 1)
                insights.append(f"Plant {pl} accounts for the highest number of reconciliation exceptions ({share}% of mismatches).")

        if delivery_col:
            dt = pd.to_datetime(mismatches[delivery_col], errors="coerce")
            if dt.notna().any():
                g = mismatches.loc[dt.notna()].copy()
                g["_dt_date"] = dt.dropna().dt.date.astype(str)
                top = g["_dt_date"].value_counts().head(3)
                if not top.empty:
                    insights.append(f"Delivery/Date {top.index[0]} shows concentrated failures ({int(top.iloc[0])} records).")

        if bu_col:
            top = mismatches[bu_col].fillna("Unknown").astype(str).value_counts().head(3)
            if not top.empty:
                bu = str(top.index[0])
                share = round(float(top.iloc[0] / max(1, len(mismatches)) * 100.0), 1)
                insights.append(f"Most mismatches are concentrated in business unit {bu} ({share}% of all exceptions).")

        if "Remarks" in mismatches.columns:
            remarks = mismatches["Remarks"].fillna("").astype(str)
            missing = int(remarks.str.contains("MISSING IN TARGET", case=False, na=False).sum())
            extra = int(remarks.str.contains("EXTRA IN TARGET", case=False, na=False).sum())
            qty = int(remarks.str.contains("QTY MISMATCH", case=False, na=False).sum())

            if missing > 0 and missing >= extra and missing >= qty:
                insights.append("A large portion of missing records suggests gaps between source and target master/inventory mapping.")
            elif extra > 0 and extra >= missing and extra >= qty:
                insights.append("Extra records indicate potential surplus data in the target system or differences in filtering logic.")
            elif qty > 0:
                insights.append("Repeated quantity mismatches point to integration or unit-of-measure/quantity alignment issues.")

        return self._dedupe_insights(insights)

    def _risk_based_insights(self, missing_in_target: int, extra_in_target: int, qty_mismatch: int, severity: str) -> list[str]:
        insights: list[str] = []

        if qty_mismatch >= max(missing_in_target, extra_in_target) and qty_mismatch > 0:
            insights.append("Repeated quantity mismatches indicate potential integration issues between SAP and the target system (quantity/unit alignment).")
        if missing_in_target >= max(extra_in_target, qty_mismatch) and missing_in_target > 0:
            insights.append("Missing records are likely to impact fulfillment planning and demand/supply alignment.")
        if extra_in_target >= max(missing_in_target, qty_mismatch) and extra_in_target > 0:
            insights.append("Extra records may lead to overstatement of inventory availability and downstream planning distortions.")

        if severity == "High":
            insights.append("High exception volume increases the risk of incorrect reporting; prioritize issue triage and system reconciliation rules before sign-off.")
        elif severity == "Medium":
            insights.append("Moderate exception volume suggests review of mapping rules and reconciliation filters to prevent recurring mismatches.")

        return insights

    def _trend_detection(self, full_df: pd.DataFrame, mismatches: pd.DataFrame) -> tuple[str | None, list[dict]]:
        if full_df is None or full_df.empty or mismatches is None or mismatches.empty:
            return None, []

        date_col = self._detect_column(full_df, ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"])
        if not date_col:
            return None, []

        all_dates = pd.to_datetime(full_df[date_col], errors="coerce")
        mism_dates = pd.to_datetime(mismatches[date_col], errors="coerce") if date_col in mismatches.columns else None
        if mism_dates is None or not mism_dates.notna().any():
            return None, []

        valid = all_dates.dropna()
        if valid.empty:
            return None, []

        span_days = int((valid.max() - valid.min()).days) if valid.max() is not pd.NaT and valid.min() is not pd.NaT else 0
        if span_days >= 28:
            period = "W"
        elif span_days >= 7:
            period = "W-SUN"
        else:
            period = "D"

        m_valid_mask = mism_dates.notna()
        m_dates = mism_dates[m_valid_mask]

        g = pd.DataFrame({"_date": m_dates.values})
        if period.startswith("W"):
            g["_period"] = pd.to_datetime(g["_date"]).dt.to_period("W").astype(str)
        else:
            g["_period"] = pd.to_datetime(g["_date"]).dt.strftime("%Y-%m-%d")

        counts = g["_period"].value_counts().sort_index()
        trend_points = [{"period": str(k), "mismatches": int(v)} for k, v in counts.items()]

        if len(trend_points) >= 2:
            last = trend_points[-1]["mismatches"]
            prev = trend_points[-2]["mismatches"]
            if prev > 0:
                change = round((last - prev) / prev * 100.0, 1)
            else:
                change = 100.0 if last > 0 else 0.0

            if abs(change) >= 20.0:
                return f"Mismatch volume increased by {change}% during the most recent period.", trend_points

        return None, trend_points

    def _build_charts(self, mismatches: pd.DataFrame, type_counts: dict, trend_points: list[dict]) -> dict:
        mismatch_by_type = []
        for t in ["Missing in Target", "Extra in Target", "Quantity Mismatch"]:
            v = int(type_counts.get(t, 0))
            mismatch_by_type.append({"title": t, "value": v})

        plant_col = self._detect_column(mismatches, ["plant", "werks", "location", "storagelocation"])
        mismatch_by_plant: list[dict[str, object]] = []
        if plant_col and plant_col in mismatches.columns:
            top = (
                mismatches[[plant_col]]
                .fillna("Unknown")
                .astype({plant_col: str})
                .groupby(plant_col)
                .size()
                .sort_values(ascending=False)
                .head(10)
            )
            mismatch_by_plant = [{"plant": str(k), "mismatches": int(v)} for k, v in top.items()]

        material_col = self._detect_column(mismatches, ["material", "matnr", "product", "item", "sku"])
        top_materials: list[dict[str, object]] = []
        if material_col and material_col in mismatches.columns:
            top = (
                mismatches[[material_col]]
                .fillna("Unknown")
                .astype({material_col: str})
                .groupby(material_col)
                .size()
                .sort_values(ascending=False)
                .head(10)
            )
            top_materials = [{"material": str(k), "mismatches": int(v)} for k, v in top.items()]

        return {
            "mismatchByType": mismatch_by_type,
            "mismatchByPlant": mismatch_by_plant,
            "topMaterials": top_materials,
            "trend": trend_points,
        }

    # ----------------------------
    # Utilities (Phase 1)
    # ----------------------------
    def _extract_top_dimension_values(self, df: pd.DataFrame, candidate_cols: list[str], max_items: int = 10) -> list[str]:
        if df is None or df.empty:
            return []
        col = self._detect_column(df, candidate_cols)
        if not col or col not in df.columns:
            return []
        top = (
            df[[col]]
            .fillna("Unknown")
            .astype({col: str})
            .groupby(col)
            .size()
            .sort_values(ascending=False)
            .head(max_items)
        )
        return [str(k) for k in top.index.tolist() if str(k)]

    def _estimate_trend_growth(self, full_df: pd.DataFrame, mismatches: pd.DataFrame) -> float:
        trend_insight, trend_points = self._trend_detection(full_df, mismatches)
        if trend_points and len(trend_points) >= 2:
            last = trend_points[-1].get("mismatches", 0)
            prev = trend_points[-2].get("mismatches", 0)
            if prev > 0:
                return round((last - prev) / prev * 100.0, 1)
            return 100.0 if last > 0 else 0.0
        if isinstance(trend_insight, str) and "increased by" in trend_insight:
            try:
                num = trend_insight.split("increased by", 1)[1].split("%", 1)[0].strip()
                return float(num)
            except Exception:
                return 0.0
        return 0.0

    def _generate_executive_summary(
        self,
        accuracy: float,
        mismatched_records: int,
        dominant_mismatch_category: str,
        severity: str,
        affected_plants: list[str],
        affected_materials: list[str],
    ) -> dict:
        accuracy = float(accuracy or 0.0)
        mismatched_records = int(mismatched_records or 0)

        affected_plants_count = len(affected_plants) if affected_plants else 0
        affected_materials_count = len(affected_materials) if affected_materials else 0

        if mismatched_records <= 0 or accuracy >= 95.0:
            text = (
                f"Reconciliation performance is within acceptable thresholds at {accuracy}% accuracy. "
                f"Exceptions are limited and predominantly related to {dominant_mismatch_category.lower()}."
            )
            if affected_plants_count:
                text += f" Affected scope includes {affected_plants_count} plant(s)."
            if affected_materials_count:
                text += f" Key impacted materials include {affected_materials_count} item(s)."
            return {"text": text}

        affected_scope_bits: list[str] = []
        if affected_plants_count:
            affected_scope_bits.append(f"{affected_plants_count} plant(s)")
        if affected_materials_count:
            affected_scope_bits.append(f"{affected_materials_count} material(s)")
        affected_scope = ", ".join(affected_scope_bits) if affected_scope_bits else "multiple operational dimensions"

        if severity == "High":
            text = (
                f"Reconciliation performance is critically below acceptable thresholds with only {accuracy}% accuracy and {mismatched_records} exception(s). "
                f"Missing target records are the dominant exception category and may impact inventory visibility, planning accuracy, and downstream fulfillment processes. "
                f"The issue spans {affected_scope}."
            )
            if dominant_mismatch_category.lower().startswith("extra"):
                text = text.replace("Missing target records", "extra/target records")
            elif dominant_mismatch_category.lower().startswith("quantity"):
                text = text.replace("Missing target records", "quantity alignment")
            return {"text": text}

        text = (
            f"Reconciliation performance is below acceptable thresholds at {accuracy}% accuracy with {mismatched_records} records requiring attention. "
            f"{dominant_mismatch_category.lower()} is the dominant exception category and can affect inventory planning reliability and downstream reporting confidence. "
            f"Affected scope includes {affected_scope}."
        )
        return {"text": text}

    def _generate_risk_score(
        self,
        accuracy: float,
        mismatch_count: int,
        affected_plants: list[str],
        affected_materials: list[str],
        trend_growth: float,
        mismatch_percentage: float,
    ) -> dict:
        accuracy = float(accuracy or 0.0)
        mismatch_percentage = float(mismatch_percentage or 0.0)

        affected_plants_count = len(affected_plants) if affected_plants else 0
        affected_materials_count = len(affected_materials) if affected_materials else 0

        risk = 0.0
        risk += (100.0 - accuracy) * 0.5
        risk += mismatch_percentage * 0.3
        risk += affected_plants_count * 2
        risk += affected_materials_count * 1

        if trend_growth is not None and trend_growth > 0:
            risk += min(100.0, float(trend_growth)) * 0.1

        risk = min(100, round(risk))

        if 0 <= risk <= 25:
            category = "Low"
        elif 26 <= risk <= 50:
            category = "Medium"
        elif 51 <= risk <= 75:
            category = "High"
        else:
            category = "Critical"

        drivers: list[str] = []
        if accuracy < 90:
            drivers.append("Low Accuracy")
        if mismatch_percentage >= 10:
            drivers.append("High Exception Volume")
        if affected_plants_count >= 5:
            drivers.append("Broad Plant Footprint")
        if affected_materials_count >= 10:
            drivers.append("Widespread Material Impact")
        if trend_growth is not None and trend_growth >= 20:
            drivers.append("Rising Trend")

        if not drivers:
            drivers = ["Stable Reconciliation Profile"]

        return {"score": int(risk), "category": category, "drivers": drivers[:5]}

    def _generate_root_causes(self, missing_in_target: int, extra_in_target: int, qty_mismatch: int, mismatches: pd.DataFrame) -> list[dict]:
        total = max(0, int(missing_in_target + extra_in_target + qty_mismatch))
        top_missing = missing_in_target >= extra_in_target and missing_in_target >= qty_mismatch and missing_in_target > 0
        top_extra = extra_in_target >= missing_in_target and extra_in_target >= qty_mismatch and extra_in_target > 0
        top_qty = qty_mismatch > 0 and qty_mismatch >= missing_in_target and qty_mismatch >= extra_in_target

        causes: list[dict] = []

        if top_qty:
            causes.append({
                "cause": "Integration Failure",
                "confidence": min(95, 70 + int(min(qty_mismatch, 1000) / max(1, total) * 25)),
                "reason": "Quantity mismatches are distributed across the reconciliation exception set, indicating quantity/unit alignment problems between source and target.",
            })
        if top_missing:
            causes.append({
                "cause": "Mapping or Synchronization Issue",
                "confidence": min(95, 70 + int(min(missing_in_target, 1000) / max(1, total) * 25)),
                "reason": "Missing records represent the majority of reconciliation failures and may indicate gaps in mapping or synchronization between systems.",
            })
        if top_extra:
            causes.append({
                "cause": "Master Data Issue",
                "confidence": min(90, 65 + int(min(extra_in_target, 1000) / max(1, total) * 20)),
                "reason": "Extra records dominate exceptions, which can point to differences in filtering logic or surplus/overlapping master data keys in the target.",
            })

        plant_col = self._detect_column(mismatches, ["plant", "werks", "location", "storagelocation"]) if mismatches is not None else None
        material_col = self._detect_column(mismatches, ["material", "matnr", "product", "item", "sku"]) if mismatches is not None else None

        if plant_col and mismatches is not None and not mismatches.empty:
            plant_top_share = round(
                float(mismatches[plant_col].fillna("Unknown").astype(str).value_counts().head(1).iloc[0]) / max(1, len(mismatches)) * 100.0,
                1,
            )
            if plant_top_share >= 35:
                causes.append({
                    "cause": "Timing Delay",
                    "confidence": 80,
                    "reason": "Exceptions are heavily concentrated in a limited plant footprint, consistent with delayed loads or site-specific update timing.",
                })

        if material_col and mismatches is not None and not mismatches.empty:
            mat_top_share = round(
                float(mismatches[material_col].fillna("Unknown").astype(str).value_counts().head(1).iloc[0]) / max(1, len(mismatches)) * 100.0,
                1,
            )
            if mat_top_share >= 30:
                causes.append({
                    "cause": "Master Data Issue",
                    "confidence": 78,
                    "reason": "Exceptions are concentrated on a small set of materials, suggesting master data gaps or inconsistent item mapping.",
                })

        if not causes:
            causes = [{"cause": "Source Data Quality Issue", "confidence": 60, "reason": "Mismatch markers indicate reconciliation failures; underlying root causes likely relate to data quality or transformation rules."}]

        dedup: dict[str, dict] = {}
        for c in causes:
            existing = dedup.get(c["cause"])
            if not existing or int(c.get("confidence", 0)) > int(existing.get("confidence", 0)):
                dedup[c["cause"]] = c

        return sorted(dedup.values(), key=lambda x: int(x.get("confidence", 0)), reverse=True)[:3]

    def _generate_business_impacts(self, root_causes: list[dict], missing_in_target: int, extra_in_target: int, qty_mismatch: int) -> list[dict]:
        impacts: list[dict] = []

        dominant_missing = missing_in_target >= extra_in_target and missing_in_target >= qty_mismatch and missing_in_target > 0
        dominant_extra = extra_in_target >= missing_in_target and extra_in_target >= qty_mismatch and extra_in_target > 0
        dominant_qty = qty_mismatch > 0 and qty_mismatch >= missing_in_target and qty_mismatch >= extra_in_target

        def add(area: str, severity: str, impact: str):
            impacts.append({"area": area, "severity": severity, "impact": impact})

        if dominant_missing:
            add("Inventory Planning", "High", "Missing records may distort inventory availability calculations and reduce confidence in planning inputs.")
            add("Supply Chain", "High", "Gaps in target coverage can break downstream supply allocation and replenishment signals.")
            add("Production Planning", "Medium", "Incomplete reconciliation may cause erroneous work allocation due to incorrect item availability assumptions.")

        if dominant_extra:
            add("Inventory Planning", "High", "Extra records can inflate inventory availability and mislead planners about stock readiness.")
            add("Procurement", "Medium", "Overstated inventory may suppress or mis-time purchase orders, impacting service levels.")
            add("Finance", "Medium", "Reconciliation drift can increase risk of cost/valuation errors driven by inaccurate master-to-transaction alignment.")

        if dominant_qty:
            add("Compliance", "High", "Quantity alignment issues can affect auditability of reconciliation results and downstream statutory reporting correctness.")
            add("Production Planning", "High", "Unit/quantity mismatches may result in incorrect execution quantities and production variance.")
            add("Supply Chain", "Medium", "Mismatch-driven availability signals can cause fulfillment delays and incorrect allocations.")

        causes = {c.get("cause") for c in (root_causes or []) if isinstance(c, dict)}
        if "Mapping or Synchronization Issue" in causes and not dominant_missing:
            add("Supply Chain", "Medium", "Mapping/synchronization patterns suggest coverage drift that may impact allocation and replenishment decisions.")
        if "Integration Failure" in causes and not dominant_qty:
            add("Inventory Planning", "Medium", "Integration patterns indicate potential quantity/unit transformation issues that can degrade planning accuracy.")

        if not impacts:
            add("Inventory Planning", "Medium", "Observed reconciliation exceptions may create planning uncertainty until root cause patterns are resolved.")

        severity_rank = {"High": 3, "Medium": 2, "Low": 1}
        return sorted(impacts, key=lambda x: severity_rank.get(x.get("severity"), 1), reverse=True)[:6]

    def _generate_recommendations(self, root_causes: list[dict], risk: dict, severity: str) -> list[dict]:
        recs: list[dict] = []
        drivers = set(risk.get("drivers", [])) if isinstance(risk, dict) else set()
        causes = [c.get("cause") for c in (root_causes or []) if isinstance(c, dict)]

        def add(priority: int, title: str, owner: str, impact: str, expected: str):
            recs.append({
                "priority": priority,
                "title": title,
                "owner": owner,
                "impact": impact,
                "expectedImprovement": expected,
            })

        if any(c in causes for c in ["Mapping or Synchronization Issue"]):
            add(1, "Validate Missing Records", "SAP Integration Team", "High", "+15% Accuracy")
            add(2, "Review Mapping Coverage Rules", "Data Integration Team", "High", "+10% Accuracy")

        if any(c in causes for c in ["Integration Failure"]):
            add(1 if not recs else len(recs) + 1, "Verify Quantity/Unit Alignment", "SAP Integration Team", "High", "+12% Accuracy")
            add(2 if len(recs) < 2 else len(recs) + 1, "Audit Unit-of-Measure Transformations", "Master Data Team", "Medium", "+8% Accuracy")

        if any(c in causes for c in ["Master Data Issue"]):
            add(len(recs) + 1, "Reconcile Master Data Keys", "Master Data Governance", "Medium", "+7% Accuracy")

        if "High Exception Volume" in drivers and not any(r.get("title") == "Triage Exception Types" for r in recs):
            add(len(recs) + 1, "Triage Exception Types", "Reconciliation Ops", "Medium", "+6% Accuracy")

        if not recs:
            add(1, "Run Targeted Data Quality Checks", "Reconciliation Ops", "Medium", "+5% Accuracy")

        recs_sorted = sorted(recs, key=lambda x: int(x.get("priority", 999)))
        for idx, r in enumerate(recs_sorted, start=1):
            r["priority"] = idx
        return recs_sorted[:5]

    # ----------------------------
    # Phase 2 (Operational + Analytics)
    # ----------------------------
    def _build_operational_intelligence(self, mismatches: pd.DataFrame, full_df: pd.DataFrame) -> dict:
        """Build Phase 2 operational/analytics intelligence.

        STRICT CONTRACT: `operationalIntelligence` MUST always contain:
        - patternIntelligence: {}
        - exceptionIntelligence: {}
        - trendIntelligence: {}
        - paretoAnalysis: {}
        - riskEntities: []
        - comparisonIntelligence: {}

        Never return missing keys; never return `undefined`.
        """

        base_contract = {
            "patternIntelligence": {},
            "exceptionIntelligence": {},
            "trendIntelligence": {},
            "paretoAnalysis": {},
            "riskEntities": [],
            "comparisonIntelligence": {},
        }

        if mismatches is None or mismatches.empty:
            return {
                "operationalIntelligence": base_contract,
                "dimensionInsights": [],
                "recurringIssues": [],
                "topRiskEntities": {},
                "criticalExceptions": [],
                "patterns": [],
                "comparisons": [],
                "trendInsights": [],
                "paretoAnalysis": {},
            }

        dimensions = self._detect_available_dimensions(mismatches=mismatches)

        patterns = self._pattern_detection(mismatches=mismatches, dimensions=dimensions)
        exceptions = self._exception_prioritization(mismatches=mismatches, dimensions=dimensions)
        trends = self._trend_intelligence(mismatches=mismatches, full_df=full_df, dimensions=dimensions)
        comparisons = self._comparative_analytics(mismatches=mismatches, dimensions=dimensions)
        pareto = self._pareto_analysis(mismatches=mismatches, dimensions=dimensions)
        top_risk = self._top_risk_entity_detection(mismatches=mismatches, dimensions=dimensions, full_df=full_df)

        # Normalize risk entities into an array for the strict contract.
        # Current backend structure is { plants:[], materials:[], suppliers:[] }.
        risk_entities: list[dict] = []
        try:
            for bucket in ["plants", "materials", "suppliers"]:
                items = (top_risk or {}).get(bucket) or []
                for it in items:
                    if isinstance(it, dict):
                        risk_entities.append({"type": bucket, **it})
        except Exception:
            risk_entities = []

        return {
            "operationalIntelligence": {
                **base_contract,
                "dimensionCoverage": {k: (len(v) if isinstance(v, list) else 0) for k, v in dimensions.items()},
                "generatedAt": None,
                "patternIntelligence": {"patterns": patterns},
                "exceptionIntelligence": {"criticalExceptions": exceptions},
                "trendIntelligence": {"trendInsights": trends},
                "paretoAnalysis": pareto,
                "riskEntities": risk_entities,
                "comparisonIntelligence": {"comparisons": comparisons},
            },
            # Preserve existing top-level fields for backward compatibility (other UI parts may rely on them).
            "dimensionInsights": self._dimension_analysis(mismatches=mismatches, dimensions=dimensions),
            "recurringIssues": self._recurring_issue_detection(mismatches=mismatches, dimensions=dimensions),
            "topRiskEntities": top_risk,
            "criticalExceptions": exceptions,
            "patterns": patterns,
            "comparisons": comparisons,
            "trendInsights": trends,
            "paretoAnalysis": pareto,
        }


    def _detect_available_dimensions(self, mismatches: pd.DataFrame) -> dict[str, list[str]]:
        candidates = {
            "Plant": ["plant", "werks", "location", "storagelocation"],
            "Material": ["material", "matnr", "product", "item", "sku"],
            "Business Unit": ["businessunit", "business unit", "division", "bukrs", "orgunit", "org unit"],
            "Region": ["region", "countryregion", "land1", "territory"],
            "Supplier": ["supplier", "vendor", "lifnr", "vendorid"],
            "Product Group": ["productgroup", "prodgroup", "matkl"],
            "Storage Location": ["storagelocation", "sloc", "lgort"],
            "Delivery Date": ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"],
        }

        dims: dict[str, list[str]] = {}
        for logical_name, cols in candidates.items():
            col = self._detect_column(mismatches, cols)
            if col:
                dims[logical_name] = [col]
        return dims

    def _dimension_analysis(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        total = len(mismatches)
        if total == 0:
            return []

        out: list[dict] = []
        for logical_dim, cols in dimensions.items():
            col = cols[0]
            vc = mismatches[col].fillna("Unknown").astype(str).value_counts()
            if vc.empty:
                continue

            value, count = vc.head(1).index[0], vc.head(1).iloc[0]
            mismatch_count = int(count)
            share = mismatch_count / total

            risk = "Low"
            if share >= 0.4:
                risk = "High"
            elif share >= 0.2:
                risk = "Medium"

            out.append({
                "dimension": logical_dim,
                "value": str(value),
                "mismatches": mismatch_count,
                "risk": risk,
                "trend": self._infer_trend_for_dimension(mismatches=mismatches, col=col, value=value),
            })

        return out

    def _infer_trend_for_dimension(self, mismatches: pd.DataFrame, col: str, value) -> str:
        date_col = self._detect_column(mismatches, ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"])
        if not date_col or date_col not in mismatches.columns:
            return "Stable"

        dt = pd.to_datetime(mismatches[date_col], errors="coerce")
        mask = dt.notna()
        if not mask.any():
            return "Stable"

        sub = mismatches.loc[mask].copy()
        sub["_dt"] = dt.loc[mask]
        sub = sub[sub[col].fillna("Unknown").astype(str) == str(value)]
        if sub.empty:
            return "Stable"

        valid = sub["_dt"].dropna()
        span_days = int((valid.max() - valid.min()).days) if valid.max() is not pd.NaT and valid.min() is not pd.NaT else 0
        if span_days >= 28:
            sub["_p"] = sub["_dt"].dt.to_period("W").astype(str)
        else:
            sub["_p"] = sub["_dt"].dt.strftime("%Y-%m-%d")

        counts = sub["_p"].value_counts().sort_index()
        if len(counts) < 2:
            return "Stable"

        last = int(counts.iloc[-1])
        prev = int(counts.iloc[-2])
        if prev == 0:
            return "Increasing" if last > 0 else "Stable"

        change = (last - prev) / prev
        if change >= 0.25:
            return "Increasing"
        if change <= -0.25:
            return "Decreasing"
        return "Stable"

    def _recurring_issue_detection(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        total = len(mismatches)
        if total == 0:
            return []

        out: list[dict] = []
        for logical_dim in ["Plant", "Material", "Business Unit", "Supplier", "Product Group", "Storage Location", "Region"]:
            cols = dimensions.get(logical_dim)
            if not cols:
                continue
            col = cols[0]
            vc = mismatches[col].fillna("Unknown").astype(str).value_counts().head(3)
            for entity, freq in vc.items():
                freq_i = int(freq)
                share = freq_i / total
                recurrence_score = round(min(100.0, share * 100.0), 1)
                severity = "High" if share >= 0.4 else ("Medium" if share >= 0.2 else "Low")

                out.append({
                    "entity": str(entity),
                    "frequency": freq_i,
                    "recurrenceScore": recurrence_score,
                    "risk": "High" if severity == "High" else ("Medium" if severity == "Medium" else "Low"),
                    "severity": severity,
                    "dimension": logical_dim,
                    "trend": self._infer_trend_for_dimension(mismatches=mismatches, col=col, value=entity),
                })

        return sorted(out, key=lambda x: float(x.get("recurrenceScore", 0)), reverse=True)[:8]

    def _top_risk_entity_detection(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]], full_df: pd.DataFrame) -> dict:
        total = len(mismatches)
        if total == 0:
            return {"plants": [], "materials": [], "suppliers": []}

        def build(col: str, limit: int) -> list[dict]:
            if col not in mismatches.columns:
                return []
            vc = mismatches[col].fillna("Unknown").astype(str).value_counts().head(limit)
            res = []
            for entity, cnt in vc.items():
                count_i = int(cnt)
                share = count_i / total
                risk_score = int(round(min(100.0, share * 100.0 * 1.2), 0))
                trend = self._infer_trend_for_dimension(mismatches=mismatches, col=col, value=entity)
                res.append({
                    "entity": str(entity),
                    "riskScore": risk_score,
                    "mismatchCount": count_i,
                    "trend": trend,
                    "businessImpact": "Dominant mismatch concentration" if "Remarks" in mismatches.columns else "",
                })
            return res

        return {
            "plants": build(dimensions.get("Plant", [None])[0], 5),
            "materials": build(dimensions.get("Material", [None])[0], 5),
            "suppliers": build(dimensions.get("Supplier", [None])[0], 5),
        }

    def _exception_prioritization(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        if "Remarks" not in mismatches.columns:
            if not dimensions:
                return []
            first_dim_col = next(iter(dimensions.values()))[0]
            vc = mismatches[first_dim_col].fillna("Unknown").astype(str).value_counts().head(6)
            out = []
            for entity, cnt in vc.items():
                cnt_i = int(cnt)
                out.append({
                    "entity": str(entity),
                    "priority": "High" if cnt_i >= 0.2 * len(mismatches) else "Medium",
                    "score": cnt_i,
                    "repeatOccurrence": cnt_i,
                    "trend": "Stable",
                })
            return out

        remarks = mismatches["Remarks"].fillna("").astype(str)
        total = len(mismatches)

        def count(pattern: str) -> int:
            return int(remarks.str.contains(pattern, case=False, na=False).sum())

        categories = [
            ("Missing in Target", "MISSING IN TARGET"),
            ("Extra in Target", "EXTRA IN TARGET"),
            ("Quantity Mismatch", "QTY MISMATCH"),
        ]

        out: list[dict] = []
        for label, pattern in categories:
            c = count(pattern)
            if c <= 0:
                continue
            share = c / total
            risk_score = int(round(min(100.0, share * 100.0 * 1.1), 0))
            priority = "Critical" if risk_score >= 70 else ("High" if risk_score >= 40 else ("Medium" if risk_score >= 20 else "Low"))
            out.append({
                "category": label,
                "priority": priority,
                "score": risk_score,
                "financialExposure": round(risk_score * 10000, 0),
                "repeatOccurrence": c,
                "trendAcceleration": "Increasing" if risk_score >= 50 else "Stable",
                "affectedBusinessArea": "Operational Fulfillment",
            })

        return sorted(out, key=lambda x: int(x.get("score", 0)), reverse=True)[:10]

    def _pattern_detection(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        patterns: list[dict] = []
        if not dimensions:
            return patterns

        # single-dimension concentration
        for logical_dim, cols in dimensions.items():
            col = cols[0]
            vc = mismatches[col].fillna("Unknown").astype(str).value_counts()
            if vc.empty:
                continue
            top_val = vc.index[0]
            top_share = float(vc.iloc[0] / max(1, len(mismatches)))
            if top_share >= 0.3:
                patterns.append({
                    "pattern": f"{round(top_share * 100)}% of {logical_dim} exceptions originate from {top_val}.",
                    "confidence": int(round(min(100.0, top_share * 200.0), 0)),
                })

        # simple cross-dimension cluster (top plant & top material)
        plant_col = dimensions.get("Plant", [None])[0]
        mat_col = dimensions.get("Material", [None])[0]
        if plant_col and mat_col and plant_col in mismatches.columns and mat_col in mismatches.columns:
            plant_top = mismatches[plant_col].fillna("Unknown").astype(str).value_counts().head(2)
            mat_top = mismatches[mat_col].fillna("Unknown").astype(str).value_counts().head(2)
            if not plant_top.empty and not mat_top.empty:
                p_val = str(plant_top.index[0])
                m_val = str(mat_top.index[0])
                inter = mismatches[
                    (mismatches[plant_col].fillna("Unknown").astype(str) == p_val)
                    & (mismatches[mat_col].fillna("Unknown").astype(str) == m_val)
                ]
                inter_share = len(inter) / max(1, len(mismatches))
                if inter_share >= 0.15:
                    patterns.append({
                        "pattern": f"Joint cluster detected: {round(inter_share * 100)}% of exceptions are for plant {p_val} and material {m_val}.",
                        "confidence": int(round(min(100.0, inter_share * 300.0), 0)),
                    })

        return sorted(patterns, key=lambda x: int(x.get("confidence", 0)), reverse=True)[:8]

    def _comparative_analytics(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        comps: list[dict] = []

        plant_col = dimensions.get("Plant", [None])[0]
        if plant_col and plant_col in mismatches.columns:
            vc = mismatches[plant_col].fillna("Unknown").astype(str).value_counts().head(2)
            if len(vc) == 2:
                a, b = vc.index[0], vc.index[1]
                va, vb = int(vc.iloc[0]), int(vc.iloc[1])
                variance = f"{round(((va - vb) / max(1, vb)) * 100.0, 0):+}%"
                comps.append({"entityType": "Plant", "entityA": str(a), "entityB": str(b), "variance": variance})

        sup_col = dimensions.get("Supplier", [None])[0]
        if sup_col and sup_col in mismatches.columns:
            vc = mismatches[sup_col].fillna("Unknown").astype(str).value_counts().head(2)
            if len(vc) == 2:
                a, b = vc.index[0], vc.index[1]
                va, vb = int(vc.iloc[0]), int(vc.iloc[1])
                variance = f"{round(((va - vb) / max(1, vb)) * 100.0, 0):+}%"
                comps.append({"entityType": "Supplier", "entityA": str(a), "entityB": str(b), "variance": variance})

        return comps[:6]

    def _trend_intelligence(self, mismatches: pd.DataFrame, full_df: pd.DataFrame, dimensions: dict[str, list[str]]) -> list[dict]:
        # best-effort: enterprise-level trend + optional top plant trend
        trend_insights: list[dict] = []

        date_col = self._detect_column(mismatches, ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"])
        if not date_col or date_col not in mismatches.columns:
            return []

        _, trend_points = self._trend_detection(full_df=full_df, mismatches=mismatches)
        if trend_points and len(trend_points) >= 2:
            last = int(trend_points[-1].get("mismatches", 0))
            prev = int(trend_points[-2].get("mismatches", 0))
            growth = round(((last - prev) / max(1, prev)) * 100.0, 0) if prev != 0 else (100 if last > 0 else 0)
            direction = "Increasing" if growth > 0 else ("Decreasing" if growth < 0 else "Stable")
            trend_insights.append({
                "entity": "Enterprise",
                "trend": direction,
                "growth": int(growth),
                "acceleration": "High" if abs(growth) >= 30 else "Normal",
                "recurrence": int(last),
            })

        plant_col = dimensions.get("Plant", [None])[0]
        if plant_col and plant_col in mismatches.columns:
            top_plant = mismatches[plant_col].fillna("Unknown").astype(str).value_counts().head(1)
            if not top_plant.empty:
                entity = str(top_plant.index[0])
                trend = self._infer_trend_for_dimension(mismatches=mismatches, col=plant_col, value=entity)
                filtered = mismatches[mismatches[plant_col].fillna("Unknown").astype(str) == entity]
                _, tp = self._trend_detection(full_df=full_df, mismatches=filtered) if len(filtered) else (None, [])
                growth = 0
                if tp and len(tp) >= 2:
                    last = int(tp[-1].get("mismatches", 0))
                    prev = int(tp[-2].get("mismatches", 0))
                    growth = int(round(((last - prev) / max(1, prev)) * 100.0, 0))

                trend_insights.append({
                    "entity": entity,
                    "trend": trend,
                    "growth": int(growth),
                    "acceleration": "High" if abs(growth) >= 30 else "Normal",
                    "recurrence": int(len(filtered)),
                })

        return trend_insights[:8]

    def _pareto_analysis(self, mismatches: pd.DataFrame, dimensions: dict[str, list[str]]) -> dict:
        def pareto_for(col: str | None):
            if not col or col not in mismatches.columns:
                return {"topContributors": [], "coverage80Percent": None}
            vc = mismatches[col].fillna("Unknown").astype(str).value_counts()
            total = len(mismatches)
            running = 0
            top_list = []
            reached = None
            for i, (k, v) in enumerate(vc.items()):
                cnt = int(v)
                running += cnt
                top_list.append({"entity": str(k), "mismatchCount": cnt, "share": round(cnt / max(1, total) * 100.0, 1)})
                if reached is None and running / max(1, total) >= 0.8:
                    reached = i + 1
                if i >= 19:
                    break
            return {"topContributors": top_list, "coverage80Percent": reached}

        return {
            "plants": pareto_for(dimensions.get("Plant", [None])[0]),
            "materials": pareto_for(dimensions.get("Material", [None])[0]),
            "suppliers": pareto_for(dimensions.get("Supplier", [None])[0]),
        }

    # ----------------------------
    # Utilities
    # ----------------------------
    def _empty_payload(self) -> dict:
        return {
            "summary": {},
            "executiveSummary": {},
            "risk": {},
            "rootCauses": [],
            "businessImpacts": [],
            "recommendations": [],
            "kpis": [],
            "insights": [],
            "charts": {},
            "operationalIntelligence": {},
            "dimensionInsights": [],
            "recurringIssues": [],
            "topRiskEntities": {},
            "criticalExceptions": [],
            "patterns": [],
            "comparisons": [],
            "trendInsights": [],
            "paretoAnalysis": {},
            "cockpit": {},
        }

    def _dedupe_insights(self, items: list[str]) -> list[str]:
        seen = set()
        out = []
        for i in items:
            if i not in seen:
                out.append(i)
                seen.add(i)
        return out

