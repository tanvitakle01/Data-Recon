import { useEffect, useMemo, useState } from "react";
import FileUploadCard from "./FileUploadCard";
import SAPFetchSection from "./SAPFetchSection";
import api from "../services/api";
import Mapping from "./Mapping";

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
  const [sapSourceRows, setSapSourceRows] = useState(null);
  const [mappingData, setMappingData] = useState(null);
  const [mappingLoading, setMappingLoading] = useState(false);
  const [mappingError, setMappingError] = useState(null);

  const canRunReconciliation = useMemo(() => {
    if (mode === "sap") {
      // Source comes from SAP fetch (no uploaded source file)
      return !!sapSourceRows && !!targetFile;
    }
    return !!sourceFile && !!targetFile;
  }, [mode, sapSourceRows, targetFile, sourceFile]);


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

      const response = await api.post(
        "/automap",
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        }
      );

      setMappingData(response.data);
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


  const runReconciliation = async () => {
    if (!canRunReconciliation) return;

    setReconError(null);
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

      const response = await api.post("/reconcile", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      // TEMP DEBUG: inspect the exact /reconcile response shape
      console.log("RECON RESPONSE", response.data);
      console.log("has summary?", !!response.data?.summary);
      console.log("has mapping?", !!response.data?.mapping);
      console.log("has columns?", !!response.data?.columns);
      console.log("has results array?", Array.isArray(response.data?.results));
      console.log(
        "results length",
        Array.isArray(response.data?.results) ? response.data.results.length : 0,
      );

      setResult(response.data);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setReconError(typeof detail === "string" ? detail : "Reconciliation failed");
    } finally {
      setReconLoading(false);
    }
  };

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Step 1 — Select Data Source</h3>

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="radio"
            value="excel"
            checked={mode === "excel"}
            onChange={() => {
              setMode("excel");
              setResult(null);
              setReconError(null);
            }}
          />
          Excel Upload
        </label>

        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="radio"
            value="sap"
            checked={mode === "sap"}
            onChange={() => {
              setMode("sap");
              setResult(null);
              setReconError(null);
            }}
          />
          SAP APIs
        </label>
      </div>

      {mode === "excel" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <FileUploadCard
              title="Source File"
              onLoaded={(d, file, meta) => {
                setSourceFile(file);
                setSourceMeta(meta ?? null);

                setResult(null);
                setReconError(null);

                setMappingData(null);
                setMappingError(null);
              }}
            />

            <FileUploadCard
              title="Target File"
              onLoaded={(d, file, meta) => {
                setTargetFile(file);
                setTargetMeta(meta ?? null);

                setResult(null);
                setReconError(null);

                setMappingData(null);
                setMappingError(null);
             }}
            />
          </div>

          <Mapping
              mappingData={mappingData}
              loading={mappingLoading}
              error={mappingError}
          />

          <div style={{ marginTop: 16 }}>
            <button
              onClick={runReconciliation}
              disabled={!canRunReconciliation || reconLoading}
              style={{
                padding: "10px 18px",
                borderRadius: 10,
                border: "1px solid #6b7280",
                background: !canRunReconciliation || reconLoading ? "#f3f4f6" : "#111827",
                color: !canRunReconciliation || reconLoading ? "#6b7280" : "white",
                cursor: !canRunReconciliation || reconLoading ? "not-allowed" : "pointer",
              }}
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

          {result?.results && (
            <div style={{ marginTop: 16 }}>
              <ReconciliationResults results={result} />
            </div>
          )}
        </div>
      )}

      {mode === "sap" && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Source System — SAP S/4</div>
          </div>
          <SAPFetchSection
            onSourceLoaded={(loadedSource) => {
              // Store fetched SAP preview rows so reconciliation can use them.
              // loadedSource.preview is already limited to first 10 rows.
              setSapSourceRows((loadedSource && loadedSource.preview) || null);
              setResult(null);
              setReconError(null);
            }}
          />


          {/* Target side remains unchanged (Excel IBP upload) */}
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 16 }}>
              <FileUploadCard
                title="Target File — IBP"
                accept=".xlsx,.xls"
                onLoaded={(d, file, meta) => {
                  setTargetFile(file);
                  setTargetMeta(meta ?? null);
                  setResult(null);
                  setReconError(null);
                }}
              />
            </div>

            <div style={{ marginTop: 16 }}>
              <button
                onClick={async () => {
                  // Keep existing engine; switch backend to SAP mode only.
                  setReconError(null);
                  setReconLoading(true);
                  setResult(null);
                  try {
                    const formData = new FormData();
                    formData.append("source_mode", "sap");
                    formData.append("target_mode", "sap");

                    // Pass SAP preview rows as source dataset so backend reconciliation uses them.
                    if (sapSourceRows) {
                      formData.append("source_rows", JSON.stringify(sapSourceRows));
                    }

                    const sheet_name_target = targetMeta?.sheet_name ?? null;
                    if (sheet_name_target) formData.append("sheet_name_target", sheet_name_target);

                    const response = await api.post("/reconcile", formData, {
                      headers: { "Content-Type": "multipart/form-data" },
                    });
                    setResult(response.data);
                  } catch (e) {
                    const detail = e?.response?.data?.detail;
                    setReconError(typeof detail === "string" ? detail : "Reconciliation failed");
                  } finally {
                    setReconLoading(false);
                  }
                }}
                disabled={!canRunReconciliation || reconLoading}

                style={{
                  padding: "10px 18px",
                  borderRadius: 10,
                  border: "1px solid #6b7280",
                  background: !targetFile || reconLoading ? "#f3f4f6" : "#111827",
                  color: !targetFile || reconLoading ? "#6b7280" : "white",
                  cursor: !targetFile || reconLoading ? "not-allowed" : "pointer",
                }}
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

            {result?.results && (
              <div style={{ marginTop: 16 }}>
                <ReconciliationResults results={result} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default UploadSection;





