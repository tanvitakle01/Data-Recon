from __future__ import annotations

from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from excel_comparator.core.auto_mapper import auto_map_columns
from excel_comparator.core.comparator import ExcelComparator
from excel_comparator.core.loader import load_excel
from excel_comparator.core.mapper import ColumnMapper
from excel_comparator.core.writer import write_annotated_excel
from excel_comparator.utils.helpers import classify_remark, get_output_filename
from API_conn.services.reconcilation_service import ReconciliationService

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_icon="📊", page_title="Data Reconcilation Module")

st.markdown(
    """
<style>
/* ── Fonts ──────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', system-ui, sans-serif;
    background: #F0F2F5;
}

/* ── Sidebar ────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #0D1117;
    border-right: 1px solid #1C2333;
}
[data-testid="stSidebar"] * { color: #8B949E !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #E6EDF3 !important; }

/* ── Main canvas ────────────────────────────────────────────────────── */
.main .block-container {
    padding: 2rem 2.5rem;
    max-width: 1280px;
}

/* ── Page title ─────────────────────────────────────────────────────── */
h1 {
    font-size: 4.20rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    color: #0D1117 !important;
    margin-bottom: 0.15rem !important;
}

/* ── Caption / subtitle ─────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p,
.caption {
    font-size: 0.8rem !important;
    color: #6B7280 !important;
    font-weight: 400 !important;
}

/* ── Section headers (subheader) ────────────────────────────────────── */
h2 {
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #6B7280 !important;
    margin-top: 2rem !important;
    margin-bottom: 0.5rem !important;
}

/* ── Divider ────────────────────────────────────────────────────────── */
hr {
    border: none !important;
    border-top: 1px solid #E5E7EB !important;
    margin: 1.5rem 0 !important;
}

/* ── Radio (data source toggle) ─────────────────────────────────────── */
[data-testid="stRadio"] > div {
    gap: 0 !important;
    display: flex !important;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 4px;
    width: fit-content;
}
[data-testid="stRadio"] label {
    padding: 6px 18px !important;
    border-radius: 6px !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: #6B7280 !important;
    cursor: pointer !important;
    transition: background 0.15s, color 0.15s !important;
}
[data-testid="stRadio"] [aria-checked="true"] + div label,
[data-testid="stRadio"] input:checked ~ div label {
    background: #111827 !important;
    color: #FFFFFF !important;
}

/* ── File uploader ──────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border: 1.5px dashed #D1D5DB !important;
    border-radius: 10px !important;
    background: #FFFFFF !important;
    padding: 1.25rem !important;
    transition: border-color 0.2s !important;
}
[data-testid="stFileUploader"]:hover {
    border-color: #6366F1 !important;
}
[data-testid="stFileUploader"] label {
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: #374151 !important;
}
[data-testid="stFileUploader"] small {
    font-size: 0.74rem !important;
    color: #9CA3AF !important;
}

/* ── Success / error / warning banners ──────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 0.8rem !important;
    padding: 10px 14px !important;
    border: none !important;
}
[data-testid="stAlert"][data-baseweb="notification"] {
    background: #F0FDF4 !important;
    color: #166534 !important;
}

/* ── Expander ───────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    background: #FFFFFF !important;
    margin-top: 8px !important;
}
[data-testid="stExpander"] summary {
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    color: #374151 !important;
    padding: 10px 14px !important;
}

/* ── Table (mapping) ────────────────────────────────────────────────── */
table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.8rem !important;
    font-family: 'IBM Plex Mono', monospace !important;
    background: #FFFFFF !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    border: 1px solid #E5E7EB !important;
}
thead tr {
    background: #F9FAFB !important;
    border-bottom: 1px solid #E5E7EB !important;
}
thead th {
    padding: 10px 16px !important;
    font-weight: 600 !important;
    font-size: 0.7rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #6B7280 !important;
    text-align: left !important;
}
tbody td {
    padding: 9px 16px !important;
    border-bottom: 1px solid #F3F4F6 !important;
    color: #111827 !important;
}
tbody tr:last-child td { border-bottom: none !important; }
tbody tr:hover td { background: #F9FAFB !important; }

/* ── Primary button (Run) ───────────────────────────────────────────── */
[data-testid="stButton"] > button[kind="primary"],
.stButton > button {
    background: #111827 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    padding: 10px 28px !important;
    transition: background 0.2s, box-shadow 0.2s !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover,
.stButton > button:hover {
    background: #1F2937 !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.18) !important;
}

/* ── Download button ────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    background: #6366F1 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 10px 28px !important;
    transition: background 0.2s !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background: #4F46E5 !important;
}

/* ── Progress bar ───────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div {
    background: #6366F1 !important;
    border-radius: 4px !important;
}
[data-testid="stProgress"] {
    background: #E5E7EB !important;
    border-radius: 4px !important;
    height: 4px !important;
}

/* ── Metric cards ───────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E5E7EB !important;
    border-radius: 10px !important;
    padding: 18px 20px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    color: #9CA3AF !important;
}
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 1.75rem !important;
    font-weight: 500 !important;
    color: #111827 !important;
}

/* ── Selectbox ──────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div {
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    background: #FFFFFF !important;
    font-size: 0.82rem !important;
    color: #111827 !important;
}

/* ── Dataframe ──────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #E5E7EB !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}

/* ── Spinner ────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] p {
    font-size: 0.8rem !important;
    color: #6B7280 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Session state ──────────────────────────────────────────────────────────────
for _k in ("run_output", "run_summary", "annotated_df"):
    if _k not in st.session_state:
        st.session_state[_k] = None


# ── Helpers ────────────────────────────────────────────────────────────────────
def _load_file(uploaded, sheet_key: str):
    """Load an uploaded file, with optional sheet selection."""
    if uploaded is None:
        return None
    raw = BytesIO(uploaded.getvalue())
    initial = load_excel(raw)
    active = initial["active_sheet"]
    if len(initial["sheets"]) > 1:
        active = st.selectbox(
            f"Select sheet — {uploaded.name}",
            options=initial["sheets"],
            index=initial["sheets"].index(active),
            key=sheet_key,
        )
    loaded = load_excel(BytesIO(uploaded.getvalue()), sheet_name=active)
    loaded["name"] = uploaded.name
    loaded["bytes"] = uploaded.getvalue()
    return loaded


def _safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """Cast all columns to string to prevent Arrow serialisation errors."""
    return df.astype(str)


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("Data Reconciliation Module")
st.caption(
    "  Upload source and target files. Columns are mapped automatically — no manual configuration needed."
)

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("Step 1 — Select Data Source")

data_mode = st.radio(
    "Data Source",
    ["Excel Upload", "SAP APIs"],
    horizontal=True,
    label_visibility="collapsed",
)

source_payload = None
target_payload = None

# =====================================================
# EXCEL MODE
# =====================================================
if data_mode == "Excel Upload":

    col_src, col_tgt = st.columns(2)

    with col_src:
        src_file = st.file_uploader(
            "Source File (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="src_upload",
        )

        if src_file:
            try:
                source_payload = _load_file(src_file, "src_sheet")

                st.success(
                    f"{source_payload['name']} — "
                    f"{source_payload['row_count']:,} rows × "
                    f"{source_payload['col_count']} cols"
                )

                with st.expander("Preview Source"):
                    st.dataframe(
                        _safe_df(source_payload["df"].head(5)),
                        use_container_width=True,
                    )

            except ValueError as exc:
                st.error(str(exc))

    with col_tgt:
        tgt_file = st.file_uploader(
            "Target File — IBP (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="tgt_upload",
        )

        if tgt_file:
            try:
                target_payload = _load_file(tgt_file, "tgt_sheet")

                st.success(
                    f"{target_payload['name']} — "
                    f"{target_payload['row_count']:,} rows × "
                    f"{target_payload['col_count']} cols"
                )

                with st.expander("Preview Target"):
                    st.dataframe(
                        _safe_df(target_payload["df"].head(5)),
                        use_container_width=True,
                    )

            except ValueError as exc:
                st.error(str(exc))

            except PermissionError:
                st.error("Please close the target file and retry.")


# =====================================================
# SAP MODE
# =====================================================
else:

    if st.button("Fetch from SAP"):

        try:
            service = ReconciliationService()

            source_df = service.get_source_data()
            target_df = service.get_target_data()

            source_payload = {
                "name": "S4 API",
                "df": source_df,
                "row_count": len(source_df),
                "col_count": len(source_df.columns),
            }

            target_payload = {
                "name": "IBP API",
                "df": target_df,
                "row_count": len(target_df),
                "col_count": len(target_df.columns),
            }

            st.success(f"S/4 data loaded ({len(source_df):,} rows)")
            st.success(f"IBP data loaded ({len(target_df):,} rows)")

            with st.expander("Preview S/4 Data"):
                st.dataframe(source_df.head(5), use_container_width=True)

            with st.expander("Preview IBP Data"):
                st.dataframe(target_df.head(5), use_container_width=True)

        except Exception as e:
            st.error(f"SAP connection failed: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — AUTO-MAPPING + RUN
# ══════════════════════════════════════════════════════════════════════════════
if source_payload and target_payload:

    # ── Auto-detect mapping ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Detected Column Mapping")
    st.caption(
        "Key columns identify matching rows. The compare column is checked for quantity differences."
    )

    try:
        mapping_result = auto_map_columns(source_payload["df"], target_payload["df"])
    except Exception as exc:
        st.error(f"Auto-mapping failed: {exc}")
        st.stop()

    display_rows = mapping_result["display"]
    if not display_rows:
        st.error("No column mapping detected. Ensure columns have meaningful names.")
        st.stop()

    mapping_table = pd.DataFrame(display_rows)[["logical", "source_col", "target_col", "role"]]
    mapping_table.columns = ["Logical Field", "Source Column", "Target Column", "Role"]
    st.table(mapping_table)

    has_compare = any(r["role"] == "📊 Compare" for r in display_rows)
    if not has_compare:
        st.warning(
            "No quantity column detected. "
            "Ensure at least one column contains numeric values."
        )

    if not any(r["role"] == "🔑 Key" for r in display_rows):
        st.error("No key columns detected. Cannot proceed with comparison.")
        st.stop()

    # ── Run ────────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Step 2 — Run Comparison")

    run_clicked = st.button("Run Comparison", type="primary")

    if run_clicked:
        st.session_state.run_output = None
        st.session_state.run_summary = None
        st.session_state.annotated_df = None

        progress = st.progress(0, text="Initialising…")
        status = st.empty()

        try:
            status.info("Validating column mapping…")
            mapper = ColumnMapper(mapping_result["mapping"])
            mapper.validate(source_payload["df"], target_payload["df"])
            progress.progress(20, text="Mapping validated")

            status.info("Building composite keys…")
            comparator = ExcelComparator(source_payload["df"], target_payload["df"], mapper)
            progress.progress(40, text="Keys built")

            with st.spinner("Comparing rows…"):
                annotated_df, summary = comparator.run([1, 2, 3, 4])
            progress.progress(70, text="Comparison complete")

            status.info("Writing annotated Excel…")
            output = write_annotated_excel(
                annotated_df,
                original_target_path=BytesIO(target_payload["bytes"]),
                sheet_name=target_payload["active_sheet"],
            )
            progress.progress(90, text="File ready")

            st.session_state.annotated_df = annotated_df
            st.session_state.run_summary = summary
            st.session_state.run_output = output.getvalue()
            progress.progress(100, text="Done")
            status.success("Comparison complete.")

        except ValueError as exc:
            st.warning(str(exc))
        except PermissionError:
            st.error("Please close the target file and retry.")
        except Exception as exc:
            st.error(f"Comparison failed: {exc}")

    # ── Results ───────────────────────────────────────────────────────────────
    if st.session_state.run_summary is not None and st.session_state.annotated_df is not None:
        summary = st.session_state.run_summary
        annotated_df = st.session_state.annotated_df.copy()
        annotated_df["Scenario"] = annotated_df["Remarks"].apply(classify_remark)

        st.markdown("---")
        st.subheader("Summary Report")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Matched", summary.get("matched", 0))
        m2.metric("Qty Mismatch", summary.get("qty_mismatch", 0))
        m3.metric("Missing in Target", summary.get("missing_in_target", 0))
        m4.metric("Extra in Target", summary.get("extra_in_target", 0))



        filter_options = [
            "All",
            "MATCHED",
            "QTY MISMATCH",
            "MISSING IN TARGET",
            "EXTRA IN TARGET",
            "Unremarked",
        ]
        filter_val = st.selectbox("Filter by scenario", filter_options, key="result_filter")
        display_df = (
            annotated_df
            if filter_val == "All"
            else annotated_df[annotated_df["Scenario"] == filter_val]
        )
        st.dataframe(
            _safe_df(display_df.drop(columns=["Scenario"])),
            use_container_width=True,
        )

        st.markdown("---")
        output_name = get_output_filename(target_payload["name"])
        st.download_button(
            label="Download Annotated Target",
            data=st.session_state.run_output,
            file_name=output_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        st.caption(f"{output_name} — original target columns with remarks appended")
        st.success("Comparison complete. File ready for download.")