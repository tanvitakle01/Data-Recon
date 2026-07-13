import { useEffect, useMemo, useState } from "react";
import FileUploadCard from "./FileUploadCard";
import SAPFetchSection from "./SAPFetchSection";
import api from "../services/api";
import Mapping from "./Mapping";
import SummaryCards from "./SummaryCards";
import ReconciliationResults from "./ReconciliationResults";
import BorderGlow from "./BorderGlow";
import DateAlignmentSummary from "./DateAlignmentSummary";
import ReconciliationScopeToggle from "./ReconciliationScopeToggle";

function UploadSection() {

  const [mode, setMode] = useState("excel");

  const [sourceFile, setSourceFile] = useState(null);
  const [targetFile, setTargetFile] = useState(null);

  const [sourceMeta, setSourceMeta] = useState(null);
  const [targetMeta, setTargetMeta] = useState(null);

  const [result, setResult] = useState(null);
  const [reconLoading, setReconLoading] = useState(false);
  const [reconError, setReconError] = useState(null);

  // SAP mode source rows (must drive reconciliation)
  const [s4Rows, setS4Rows] = useState(null);
  const [ibpRows, setIBPRows] = useState(null);
  const [mappingData, setMappingData] = useState(null);
  const [mappingLoading, setMappingLoading] = useState(false);
  const [mappingError, setMappingError] = useState(null);

  // Date Range Alignment
  const [dateScope, setDateScope] = useState("overlap");
  const [dateAlignment, setDateAlignment] = useState(null);
  const [noOverlapBlock, setNoOverlapBlock] = useState(null); // holds blocking date_alignment when reconciliation is blocked
  const [overriding, setOverriding] = useState(false);

  const canRunReconciliation = useMemo(() => {
    if (mode === "sap") {
      // Source comes from SAP fetch (no uploaded source file)
      return !!s4Rows && !!ibpRows;;
    }
    return !!sourceFile && !!targetFile;
  }, [mode, s4Rows, ibpRows, targetFile, sourceFile]);


  useEffect(() => {
  const detectMapping = async () => {
    if (!sourceFile || !targetFile) return;

    try {
      setMappingLoading(true);
      setMappingError(null);

      const formData = new FormData();

      formData.append("source_file", sourceFile);
      formData.append("target_file", targetFile);

      formData.append(
        "sheet_name_source",
        sourceMeta?.sheet_name || ""
      );

      formData.append(
        "sheet_name_target",
        targetMeta?.sheet_name || ""
      );

      const response = await api.post("/automap", formData);

      setMappingData(response.data);
      setDateAlignment(response.data?.date_alignment ?? null);
    } catch (err) {
      console.error(err);

      setMappingError(
        err?.response?.data?.detail ||
        "Failed to detect mapping"
      );
    } finally {
      setMappingLoading(false);
    }
  };

  if (
    mode === "excel" &&
    sourceFile &&
    targetFile
  ) {
    detectMapping();
  }
}, [
  sourceFile,
  targetFile,
  sourceMeta,
  targetMeta,
  mode,
]);

useEffect(() => {
  const previewSapAlignment = async () => {
    if (!s4Rows || !ibpRows) return;

    try {
      const formData = new FormData();
      formData.append("source_rows", JSON.stringify(s4Rows));
      formData.append("target_rows", JSON.stringify(ibpRows));

      const response = await api.post("/api/date-alignment/preview", formData);

      setDateAlignment(response.data);
    } catch (err) {
      console.error("Date alignment preview failed:", err);
    }
  };

  if (mode === "sap") {
    previewSapAlignment();
  }
}, [s4Rows, ibpRows, mode]);


  const runReconciliation = async (override = false) => {
    if (!canRunReconciliation) return;

    setReconError(null);
    setNoOverlapBlock(null);
    if (override) setOverriding(true);
    setReconLoading(true);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("source_file", sourceFile);
      formData.append("target_file", targetFile);

      // Keep sheet selection support for Excel preview usage, but do not change payload requirements.
      const sheet_name_source = sourceMeta?.sheet_name ?? null;
      const sheet_name_target = targetMeta?.sheet_name ?? null;
      if (sheet_name_source) formData.append("sheet_name_source", sheet_name_source);
      if (sheet_name_target) formData.append("sheet_name_target", sheet_name_target);

      if (!mappingData?.mapping) {
        throw new Error(
          "Missing detected mapping. Please wait for mapping detection (or run auto-map) before reconciling."
        );
      }

      const payloadMapping = mappingData.mapping;
      const payloadMappingJson = JSON.stringify(payloadMapping);

      formData.append("mapping_json", payloadMappingJson);
      formData.append("date_scope", dateScope);
      if (override) formData.append("override_no_overlap", "true");

      const response = await api.post("/reconcile", formData);

      setResult(response.data);
      setDateAlignment(response.data?.date_alignment ?? null);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.no_overlap) {
        setNoOverlapBlock(detail.date_alignment ?? null);
      } else {
        setReconError(typeof detail === "string" ? detail : "Reconciliation failed");
      }
    } finally {
      setReconLoading(false);
      setOverriding(false);
    }
  };

  const runSapReconciliation = async (override = false) => {
    setReconError(null);
    setNoOverlapBlock(null);
    if (override) setOverriding(true);
    setReconLoading(true);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("source_mode", "s4");
      formData.append("target_mode", "ibp");

      formData.append("source_rows", JSON.stringify(s4Rows || []));
      formData.append("target_rows", JSON.stringify(ibpRows || []));
      formData.append("date_scope", dateScope);
      if (override) formData.append("override_no_overlap", "true");

      const response = await api.post("/reconcile", formData);

      setResult(response.data);
      setDateAlignment(response.data?.date_alignment ?? null);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.no_overlap) {
        setNoOverlapBlock(detail.date_alignment ?? null);
      } else {
        setReconError(typeof detail === "string" ? detail : "Reconciliation failed");
      }
    } finally {
      setReconLoading(false);
      setOverriding(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span
          style={{
            display: "inline-flex",
            height: 24,
            width: 24,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(59,130,246,0.14)",
            color: "#1d4ed8",
            fontWeight: 900,
            fontSize: 12,
          }}
        >
          1
        </span>
        <h3 style={{ margin: 0 }}>Select Data Source</h3>
      </div>

      <div
        style={{
          display: "inline-flex",
          gap: 4,
          padding: 4,
          borderRadius: 14,
          background: "rgba(148,163,184,0.14)",
          marginTop: 14,
          marginBottom: 18,
        }}
      >
        {[
          { key: "excel", label: "Excel Upload" },
          { key: "sap", label: "SAP APIs" },
        ].map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => {
              setMode(opt.key);
              setResult(null);
              setReconError(null);
              setDateAlignment(null);
              setNoOverlapBlock(null);
            }}
            style={{
              padding: "8px 16px",
              borderRadius: 10,
              border: "none",
              fontWeight: 800,
              fontSize: 13,
              cursor: "pointer",
              background: mode === opt.key ? "#fff" : "transparent",
              color: mode === opt.key ? "#0f172a" : "#64748b",
              boxShadow: mode === opt.key ? "0 4px 12px rgba(2,6,23,0.08)" : "none",
              transition: "all 160ms ease",
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {mode === "excel" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <BorderGlow>
              <FileUploadCard
                title="Source File"
                onLoaded={(d, file, meta) => {
                  setSourceFile(file);
                  setSourceMeta(meta ?? null);

                  setResult(null);
                  setReconError(null);

                  setMappingData(null);
                  setMappingError(null);

                  setDateAlignment(null);
                  setNoOverlapBlock(null);
                }}
              />
            </BorderGlow>

            <BorderGlow>
              <FileUploadCard
                title="Target File"
                onLoaded={(d, file, meta) => {
                  setTargetFile(file);
                  setTargetMeta(meta ?? null);

                  setResult(null);
                  setReconError(null);

                  setMappingData(null);
                  setMappingError(null);

                  setDateAlignment(null);
                  setNoOverlapBlock(null);
                }}
              />
            </BorderGlow>
          </div>

          <Mapping
              mappingData={mappingData}
              loading={mappingLoading}
              error={mappingError}
          />

          {(dateAlignment || noOverlapBlock) && (
            <>
              <ReconciliationScopeToggle value={dateScope} onChange={setDateScope} />
              <DateAlignmentSummary
                alignment={noOverlapBlock || dateAlignment}
                onOverride={dateScope === "overlap" ? () => runReconciliation(true) : undefined}
                overriding={overriding}
              />
            </>
          )}

          <div style={{ marginTop: 16 }}>
            <button
              onClick={() => runReconciliation(false)}
              disabled={!canRunReconciliation || reconLoading}
              className="btn-primary"
            >
              {reconLoading ? "Reconciling…" : "Run Reconciliation"}
            </button>
          </div>

          {reconError && (
            <div style={{ marginTop: 12, color: "#b91c1c" }}>⚠️ {String(reconError)}</div>
          )}

          {result?.summary && (
            <div style={{ marginTop: 16 }}>
              <SummaryCards summary={result.summary} />
            </div>
          )}

          {result?.preview_rows?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <ReconciliationResults reconResult={result} />
            </div>
          )}


        </div>
      )}

      {mode === "sap" && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 8, color: "#334155" }}>Source System — SAP S/4</div>
          </div>
          <SAPFetchSection
            onSourceLoaded={(sources) => {
              if (sources?.s4){
                setS4Rows(sources.s4.data || []);
              }
              if (sources?.ibp){
                setIBPRows(sources.ibp.data || []);
              }

              setResult(null);
              setReconError(null);
              setDateAlignment(null);
              setNoOverlapBlock(null);
            }}
          />


          {/* Target side remains unchanged (Excel IBP upload) */}
          <div style={{ marginTop: 16 }}>

            {(dateAlignment || noOverlapBlock) && (
              <>
                <ReconciliationScopeToggle value={dateScope} onChange={setDateScope} />
                <DateAlignmentSummary
                  alignment={noOverlapBlock || dateAlignment}
                  onOverride={dateScope === "overlap" ? () => runSapReconciliation(true) : undefined}
                  overriding={overriding}
                />
              </>
            )}

            <div style={{ marginTop: 16 }}>
              <button
                onClick={() => runSapReconciliation(false)}
                disabled={!canRunReconciliation || reconLoading}
                className="btn-primary"
              >
                {reconLoading ? "Reconciling…" : "Run Reconciliation"}
              </button>
            </div>

            {reconError && (
              <div style={{ marginTop: 12, color: "#b91c1c" }}>⚠️ {String(reconError)}</div>
            )}

            {result?.summary && (
              <div style={{ marginTop: 16 }}>
                <SummaryCards summary={result.summary} />
              </div>
            )}

            {result && (
              <div style={{ marginTop: 16 }}>
                <ReconciliationResults reconResult={result} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default UploadSection;





