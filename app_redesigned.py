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
from ai.mismatch_analyzer import MismatchAnalyzer
from ai.summary_generator import SummaryGenerator
from ai.reason_engine import ReasonEngine
from ai.pattern_detector import PatternDetector
from ai.root_cause_engine import RootCauseEngine

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_icon="📊", page_title="DataSync Comparator")

st.markdown(
    """
<style>
/* ---------------------------
   Lively cinematic layer
   (Animations are JS-triggered; CSS provides depth + luxury spacing.)
   --------------------------- */

:root{
  --lux-ink:#0F172A;
  --lux-muted:#475569;
  --lux-mint:#06C7B7;
  --lux-mint2:#00D4FF;
  --lux-lav:#7C3AED;
  --lux-warn:#F59E0B;
  --lux-danger:#EF4444;
  --lux-bg:#F8FAFC;
}

/* Global texture */
[data-testid="stAppViewContainer"],
[data-testid="stMain"]{
  position: relative;
}
[data-testid="stAppViewContainer"]::before{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  background:
    radial-gradient(900px 400px at 10% 0%, rgba(6,199,183,0.22), transparent 55%),
    radial-gradient(700px 340px at 85% 10%, rgba(124,58,237,0.18), transparent 55%),
    radial-gradient(500px 260px at 40% 90%, rgba(0,212,255,0.12), transparent 60%);
  z-index:-1;
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce){
  *{ animation-duration: 0.001ms !important; animation-iteration-count: 1 !important; transition-duration: 0.001ms !important; scroll-behavior:auto !important; }
}

/* Hover depth */
.stButton > button,
[data-testid="stDownloadButton"] > button,
[data-testid="stFileUploader"],
[data-testid="stMetric"],
[data-testid="stExpander"]{
  transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease, background .25s ease;
}
.stButton > button:hover,
[data-testid="stDownloadButton"] > button:hover{
  transform: translateY(-1px);
  box-shadow: 0 18px 40px rgba(6,199,183,0.18), 0 4px 18px rgba(124,58,237,0.10);
}
[data-testid="stFileUploader"]:hover,
[data-testid="stExpander"]:hover{
  transform: translateY(-1px);
  box-shadow: 0 20px 50px rgba(2,132,199,0.10);
  border-color: rgba(6,199,183,0.55) !important;
}

/* Premium cards */
[data-testid="stMetric"]{
  backdrop-filter: blur(10px);
}
[data-testid="stMetric"]::after{
  content:"";
  position:absolute;
  inset:-1px;
  border-radius: 10px;
  pointer-events:none;
  background: linear-gradient(135deg, rgba(6,199,183,0.35), rgba(124,58,237,0.18), rgba(0,212,255,0.15));
  opacity: .35;
  mask: linear-gradient(#000, #000) content-box, linear-gradient(#000, #000);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
}

<style>

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ── Reset & base ─────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main {
    font-family: 'Inter', system-ui, sans-serif;
    /* Lively + premium bright canvas */
    background: radial-gradient(1200px 600px at 20% -10%, #E8FFFB 0%, rgba(232,255,251,0) 55%),
                radial-gradient(1000px 500px at 90% 10%, #F4E9FF 0%, rgba(244,233,255,0) 60%),
                linear-gradient(180deg, #F7FAFF 0%, #EEF2FF 45%, #F8FAFC 100%) !important;
    color: #0F172A !important;
}


.main .block-container {
    padding: 2.25rem 2.75rem;
    max-width: 1320px;
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFF 100%) !important;
    border-right: 1px solid #E5E7EB !important;
}
[data-testid="stSidebar"] * { color: #475569 !important; }


/* ── Page title ───────────────────────────────────────────────────────── */
h1 {
    font-size: 1.5rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.025em !important;
    color: #F1F5F9 !important;
    margin-bottom: 0.1rem !important;
}

/* ── Caption ──────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p {
    font-size: 0.78rem !important;
    color: #475569 !important;
}

/* ── Section subheaders ───────────────────────────────────────────────── */
h2 {
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: #00FFD1 !important;
    margin-top: 2rem !important;
    margin-bottom: 0.4rem !important;
}

/* ── Divider ──────────────────────────────────────────────────────────── */
hr {
    border: none !important;
    border-top: 1px solid #ffffff08 !important;
    margin: 1.75rem 0 !important;
}

/* ── Radio pills ──────────────────────────────────────────────────────── */
[data-testid="stRadio"] > div {
    gap: 0 !important;
    display: flex !important;
    background: #0F1520;
    border: 1px solid #1E293B;
    border-radius: 8px;
    padding: 4px;
    width: fit-content;
}
[data-testid="stRadio"] label {
    padding: 6px 20px !important;
    border-radius: 6px !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    color: #475569 !important;
    cursor: pointer !important;
    transition: all 0.15s !important;
}
[data-testid="stRadio"] input:checked ~ div label {
    background: #00FFD115 !important;
    color: #00FFD1 !important;
    box-shadow: 0 0 12px #00FFD122 !important;
}

/* ── File uploader ────────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border: 1.5px dashed #1E293B !important;
    border-radius: 10px !important;
    background: #0C1220 !important;
    padding: 1.5rem !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
[data-testid="stFileUploader"]:hover {
    border-color: #00FFD150 !important;
    box-shadow: 0 0 20px #00FFD10A !important;
}
[data-testid="stFileUploader"] label {
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: #94A3B8 !important;
}
[data-testid="stFileUploader"] small {
    font-size: 0.72rem !important;
    color: #334155 !important;
}

/* ── Alerts ───────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 0.78rem !important;
    border: none !important;
    font-family: 'JetBrains Mono', monospace !important;
}
/* success */
div[data-baseweb="notification"][kind="positive"] {
    background: #001A0F !important;
    border-left: 3px solid #00FF87 !important;
    color: #00FF87 !important;
}
/* warning */
div[data-baseweb="notification"][kind="warning"] {
    background: #1A1200 !important;
    border-left: 3px solid #FFD700 !important;
    color: #FFD700 !important;
}
/* error */
div[data-baseweb="notification"][kind="negative"] {
    background: #1A0005 !important;
    border-left: 3px solid #FF2D55 !important;
    color: #FF2D55 !important;
}

/* ── Expander ─────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #1E293B !important;
    border-radius: 8px !important;
    background: #0C1220 !important;
    margin-top: 8px !important;
}
[data-testid="stExpander"] summary {
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    color: #64748B !important;
    padding: 10px 14px !important;
}
[data-testid="stExpander"] summary:hover {
    color: #00FFD1 !important;
}

/* ── Mapping table ────────────────────────────────────────────────────── */
table {
    width: 100% !important;
    border-collapse: collapse !important;
    font-size: 0.78rem !important;
    font-family: 'JetBrains Mono', monospace !important;
    background: #0C1220 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1px solid #1E293B !important;
}
thead tr {
    background: #080C12 !important;
    border-bottom: 1px solid #00FFD118 !important;
}
thead th {
    padding: 11px 18px !important;
    font-weight: 600 !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #00FFD1 !important;
    text-align: left !important;
}
tbody td {
    padding: 10px 18px !important;
    border-bottom: 1px solid #0F1825 !important;
    color: #94A3B8 !important;
}
tbody tr:last-child td { border-bottom: none !important; }
tbody tr:hover td {
    background: #00FFD108 !important;
    color: #E2E8F0 !important;
}

/* ── Primary button ───────────────────────────────────────────────────── */
[data-testid="stButton"] > button,
.stButton > button {
    background: transparent !important;
    color: #00FFD1 !important;
    border: 1.5px solid #00FFD1 !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
    padding: 10px 32px !important;
    font-family: 'JetBrains Mono', monospace !important;
    transition: all 0.2s !important;
    box-shadow: 0 0 0px #00FFD100 !important;
}
[data-testid="stButton"] > button:hover,
.stButton > button:hover {
    background: #00FFD115 !important;
    box-shadow: 0 0 24px #00FFD140, inset 0 0 12px #00FFD108 !important;
    color: #00FFD1 !important;
}

/* ── Download button ──────────────────────────────────────────────────── */
[data-testid="stDownloadButton"] > button {
    background: transparent !important;
    color: #BF5FFF !important;
    border: 1.5px solid #BF5FFF !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 10px 32px !important;
    font-family: 'JetBrains Mono', monospace !important;
    transition: all 0.2s !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background: #BF5FFF18 !important;
    box-shadow: 0 0 24px #BF5FFF44 !important;
    color: #D18DFF !important;
}

/* ── Progress bar ─────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div {
    background: #0F1825 !important;
    border-radius: 4px !important;
    height: 3px !important;
}
[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #00FFD1, #00BFFF) !important;
    border-radius: 4px !important;
    box-shadow: 0 0 8px #00FFD180 !important;
}

/* ── Metric cards ─────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #0C1220 !important;
    border: 1px solid #1E293B !important;
    border-radius: 10px !important;
    padding: 20px 22px !important;
    position: relative !important;
    overflow: hidden !important;
}
[data-testid="stMetric"]::before {
    content: '' !important;
    position: absolute !important;
    top: 0 !important; left: 0 !important; right: 0 !important;
    height: 2px !important;
    background: linear-gradient(90deg, #00FFD1, transparent) !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #334155 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 2rem !important;
    font-weight: 500 !important;
    color: #F1F5F9 !important;
    text-shadow: 0 0 20px #00FFD120 !important;
}

/* ── Selectbox ────────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div {
    border: 1px solid #1E293B !important;
    border-radius: 8px !important;
    background: #0C1220 !important;
    font-size: 0.8rem !important;
    color: #94A3B8 !important;
}
[data-testid="stSelectbox"] > div > div:focus-within {
    border-color: #00FFD150 !important;
    box-shadow: 0 0 0 2px #00FFD115 !important;
}

/* ── Dataframe ────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #1E293B !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    background: #0C1220 !important;
}

/* ── Spinner ──────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] p {
    font-size: 0.78rem !important;
    color: #475569 !important;
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Scrollbar ────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #080C12; }
::-webkit-scrollbar-thumb { background: #1E293B; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #00FFD140; }
</style>

<script>
// --- Streamlit DOM cinematic layer (GSAP-inspired) ---
(function(){
  const root = document.documentElement;

  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ensure = (fn)=>{ try{ fn(); } catch(e){} };

  // Text reveal: wrap likely headings/labels.
  ensure(function(){
    if(reduce) return;
    const targets = document.querySelectorAll('h1, h2, h3, [data-testid="stSubheader"], [data-testid="stCaptionContainer"] p');
    targets.forEach(el=>{
      const txt = (el.textContent||'').trim();
      if(!txt || el.dataset.revealDone) return;
      el.dataset.revealDone = '1';
      // If already split, skip
      if(el.querySelector('.bb-char')) return;
      el.textContent = '';
      const span = document.createElement('span');
      span.style.display = 'inline-block';
      span.style.whiteSpace = 'pre-wrap';
      const chars = Array.from(txt);
      chars.forEach((c,i)=>{
        const b = document.createElement('span');
        b.className = 'bb-char';
        b.textContent = c;
        b.style.display = c === ' ' ? 'inline-block' : 'inline-block';
        b.style.opacity = '0';
        b.style.transform = 'translate3d(0,12px,0)';
        b.style.transition = `opacity 700ms cubic-bezier(.2,.8,.2,1) ${i*12}ms, transform 700ms cubic-bezier(.2,.8,.2,1) ${i*12}ms`;
        // keep spaces
        if(c===' ') b.style.width = '0.35em';
        span.appendChild(b);
      });
      el.appendChild(span);
      // animate in
      requestAnimationFrame(()=>{
        const nodes = el.querySelectorAll('.bb-char');
        nodes.forEach(n=>{
          n.style.opacity = '1';
          n.style.transform = 'translate3d(0,0,0)';
        });
      });
    });
  });

  // Loading screen
  ensure(function(){
    if(reduce) return;
    const wrap = document.createElement('div');
    wrap.id = 'bb-loading';
    wrap.innerHTML = `
      <div class="bb-load-card">
        <div class="bb-orbit" aria-hidden="true"></div>
        <div class="bb-brand">DataSync</div>
        <div class="bb-sub">Reconciliation in motion</div>
        <div class="bb-bar"><span></span></div>
      </div>
    `;
    document.body.appendChild(wrap);
    const style = document.createElement('style');
    style.textContent = `
      #bb-loading{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(248,250,252,0.86);backdrop-filter: blur(10px);}
      #bb-loading .bb-load-card{width:min(520px,92vw);border-radius:18px;padding:28px 26px;background:rgba(255,255,255,0.78);border:1px solid rgba(15,23,42,0.08);box-shadow:0 30px 90px rgba(2,132,199,0.14), 0 10px 40px rgba(124,58,237,0.10);text-align:center;}
      #bb-loading .bb-brand{font:600 18px/1.2 Inter,system-ui;color:#0F172A;letter-spacing:-0.02em;}
      #bb-loading .bb-sub{margin-top:6px;font:500 12px/1.4 Inter,system-ui;color:#475569;}
      #bb-loading .bb-bar{margin-top:18px;height:8px;border-radius:999px;background:rgba(15,23,42,0.08);overflow:hidden;}
      #bb-loading .bb-bar span{display:block;height:100%;width:40%;border-radius:999px;background:linear-gradient(90deg,#06C7B7,#00D4FF,#7C3AED);animation:bbbar 1100ms ease-in-out infinite;}
      @keyframes bbbar{0%{transform:translateX(-80%);}50%{transform:translateX(110%);}100%{transform:translateX(250%);}}
      #bb-loading .bb-orbit{height:74px;margin:2px auto 8px;width:74px;border-radius:50%;border:1px solid rgba(15,23,42,0.10);background:radial-gradient(circle at 30% 30%, rgba(6,199,183,0.22), transparent 55%), radial-gradient(circle at 70% 40%, rgba(124,58,237,0.20), transparent 58%), rgba(255,255,255,0.55);position:relative;}
      #bb-loading .bb-orbit:before{content:"";position:absolute;inset:10px;border-radius:50%;border:2px solid rgba(0,212,255,0.35);animation:bbspin 1400ms linear infinite;}
      #bb-loading .bb-orbit:after{content:"";position:absolute;left:50%;top:50%;width:10px;height:10px;border-radius:50%;background:linear-gradient(180deg,#06C7B7,#7C3AED);transform:translate(-50%,-50%);box-shadow:0 0 26px rgba(6,199,183,0.35);}
      @keyframes bbspin{to{transform:rotate(360deg);}}
    `;
    document.head.appendChild(style);

    // Fade out once first paint happens.
    window.addEventListener('load', ()=>{
      setTimeout(()=>{
        wrap.style.transition='opacity 500ms ease, transform 500ms ease';
        wrap.style.opacity='0';
        wrap.style.transform='scale(0.98)';
        setTimeout(()=>wrap.remove(), 520);
      }, 650);
    });
  });

  // Scroll-triggered fade/scale/slide
  ensure(function(){
    if(reduce) return;
    const els = document.querySelectorAll('h2, [data-testid="stMetric"], [data-testid="stExpander"], table, [data-testid="stDataFrame"], .stPlotlyChart');
    els.forEach(el=>{
      if(el.dataset.bbScroll) return;
      el.dataset.bbScroll='1';
      el.style.opacity='0';
      el.style.transform='translate3d(0,18px,0) scale(0.98)';
      el.style.transition='opacity 800ms cubic-bezier(.2,.8,.2,1), transform 900ms cubic-bezier(.2,.8,.2,1)';
    });
    const io = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        if(!e.isIntersecting) return;
        const el = e.target;
        el.style.opacity='1';
        el.style.transform='translate3d(0,0,0) scale(1)';
        io.unobserve(el);
      });
    }, {threshold: 0.12});
    els.forEach(el=>io.observe(el));
  });

  // Floating + depth (subtle motion)
  ensure(function(){
    if(reduce) return;
    const metrics = document.querySelectorAll('[data-testid="stMetric"]');
    metrics.forEach((card,i)=>{
      card.style.willChange='transform';
      const base = 4 + (i%3);
      let t0 = performance.now();
      function tick(t){
        const dt = t - t0;
        const s1 = Math.sin(dt/900 + i)*base;
        const s2 = Math.cos(dt/1100 + i)*2;
        card.style.transform = `translate3d(0, ${-s2}px, 0)`;
        // avoid overriding hover translateY: keep hover via CSS
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  });

  // Inertia-ish scrolling: best-effort for mouse wheel
  ensure(function(){
    if(reduce) return;
    let last = 0;
    const scroller = document.querySelector('.main') || document.body;
    scroller.addEventListener('wheel', (e)=>{
      const now = Date.now();
      const dt = now - last; last = now;
      if(dt < 24) e.preventDefault();
    }, {passive:false});
  });
})();
</script>
""",
    unsafe_allow_html=True,
)


# ── Session state ──────────────────────────────────────────────────────────────
for _k in ("run_output", "run_summary", "annotated_df"):
    if _k not in st.session_state:
        st.session_state[_k] = None


# ── Helpers ────────────────────────────────────────────────────────────────────
def _load_file(uploaded, sheet_key: str):
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
    return df.astype(str)


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("Data Reconciliation")
st.caption("Upload source and target files. Columns are mapped automatically — no manual configuration needed.")

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

# ── Excel mode ─────────────────────────────────────────────────────────────────
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
                    st.dataframe(_safe_df(source_payload["df"].head(5)), use_container_width=True)
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
                    st.dataframe(_safe_df(target_payload["df"].head(5)), use_container_width=True)
            except ValueError as exc:
                st.error(str(exc))
            except PermissionError:
                st.error("Please close the target file and retry.")

# ── SAP mode ───────────────────────────────────────────────────────────────────
else:
    if st.button("Fetch from SAP"):
        try:
            service = ReconciliationService()
            source_df = service.get_source_data()
            target_df = service.get_target_data()
            source_payload = {
                "name": "S4 API", "df": source_df,
                "row_count": len(source_df), "col_count": len(source_df.columns),
            }
            target_payload = {
                "name": "IBP API", "df": target_df,
                "row_count": len(target_df), "col_count": len(target_df.columns),
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

    st.markdown("---")
    st.subheader("Detected Column Mapping")
    st.caption("Key columns identify matching rows. The compare column is checked for quantity differences.")

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
        st.warning("No quantity column detected. Ensure at least one column contains numeric values.")

    if not any(r["role"] == "🔑 Key" for r in display_rows):
        st.error("No key columns detected. Cannot proceed with comparison.")
        st.stop()

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
        
        st.write(annotated_df[["Remarks"]].head(20))

        st.markdown("---")
        st.markdown("AI Reconcilation Analysis")

        analyzer = MismatchAnalyzer()
        summary_gen = SummaryGenerator()
        reason_engine = ReasonEngine()
        pattern_detector = PatternDetector()
        root_engine = RootCauseEngine()

        stats = analyzer.analyze(summary)
        summary_text = summary_gen.generate(stats)
        reasons = reason_engine.generate(stats)
        patterns = pattern_detector.detect(stats)
        root_causes = root_engine.identify(stats)

        st.markdown("### AI Summary")
        st.write(summary_text)

        st.markdown("Possible causes")
        for reason in reasons:
            st.write("*", reason)
        
        st.markdown("Key findings")
        for p in patterns:
            st.write("*", p)
        
        st.markdown("Likely root causes")
        for r in root_causes:
            st.write("*", r)


        filter_options = ["All", "MATCHED", "QTY MISMATCH", "MISSING IN TARGET", "EXTRA IN TARGET", "Unremarked"]
        filter_val = st.selectbox("Filter by scenario", filter_options, key="result_filter")
        display_df = (
            annotated_df if filter_val == "All"
            else annotated_df[annotated_df["Scenario"] == filter_val]
        )
        st.dataframe(_safe_df(display_df.drop(columns=["Scenario"])), use_container_width=True)

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
