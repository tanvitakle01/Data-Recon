import { useRef, useState } from "react";

import api from "../services/api";
import PreviewTable from "./PreviewTable";


function FileUploadCard({
  title,
  accept = ".xlsx,.xls,.csv",
  onLoaded,
}) {
  const [fileInfo, setFileInfo] = useState(null);
  const [fileObj, setFileObj] = useState(null);
  const [selectedSheet, setSelectedSheet] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);


  const fetchPreview = async (file, sheetName = null) => {
    const formData = new FormData();
    formData.append("file", file);
    if (sheetName) formData.append("sheet_name", sheetName);

    const response = await api.post("/preview", formData);
    return response.data;
  };

  const handleFile = async (file) => {
    if (!file) return;

    setFileObj(file);
    setSelectedSheet(null);
    setError(null);
    setLoading(true);

    try {
      const data = await fetchPreview(file, null);
      setFileInfo(data);
      setShowPreview(false);

      const initialSheet = data?.active_sheet ?? null;
      setSelectedSheet(initialSheet);
      onLoaded?.(data, file, { sheet_name: initialSheet, sheets: data?.sheets ?? [] });
    } catch (e) {
      setError(e?.response?.data?.detail || "File upload failed");
      setFileInfo(null);
      setFileObj(null);
      setSelectedSheet(null);
      onLoaded?.(null);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = (event) => {
    handleFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragOver(false);
    handleFile(event.dataTransfer.files?.[0] ?? null);
  };


  return (
    <div
      className="recon-upload-card"
      style={{
        border: "1px solid rgba(229,231,235,0.85)",
        padding: 16,
        borderRadius: 14,
        background: "rgba(255,255,255,0.85)",
      }}
    >
      <h3 style={{ marginTop: 0, fontSize: 16, fontWeight: 700, color: "rgba(15,23,42,0.92)" }}>{title}</h3>


      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        style={{
          border: `1.5px dashed ${dragOver ? "#2563eb" : "rgba(148,163,184,0.6)"}`,
          borderRadius: 10,
          padding: 16,
          textAlign: "center",
          cursor: "pointer",
          background: dragOver ? "rgba(37,99,235,0.06)" : "transparent",
        }}
      >
        <div style={{ fontSize: 13, color: "#475569", fontWeight: 600 }}>
          Drag &amp; drop a file here, or click to choose
        </div>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>Accepted: .xlsx, .xls, .csv</div>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          onChange={handleUpload}
          style={{ display: "none" }}
        />
      </div>

      {loading && <div style={{ marginTop: 8 }}>Loading preview…</div>}
      {error && (
        <div style={{ marginTop: 8, color: "#b91c1c", fontSize: 13 }}>
          {error}
        </div>
      )}

      {fileInfo && (
        <div style={{ marginTop: 10 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 999,
              background: "rgba(16,185,129,0.12)",
              color: "#047857",
              fontWeight: 800,
              fontSize: 12,
            }}
          >
            ✓ {fileInfo.filename}
          </div>
          <div style={{ marginTop: 6, color: "#64748b", fontWeight: 600, fontSize: 13 }}>
            {fileInfo.rows} rows × {fileInfo.cols} cols
          </div>

          <button className="btn-secondary" style={{ marginTop: 10 }} onClick={() => setShowPreview((s) => !s)}>
            {showPreview ? "Hide Preview" : "Preview"}
          </button>


          {fileInfo?.sheets?.length > 1 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "#64748b", marginBottom: 6 }}>Sheet</div>
              <select
                value={selectedSheet ?? ""}
                onChange={async (e) => {
                  const newSheet = e.target.value;
                  setSelectedSheet(newSheet);
                  setLoading(true);
                  try {
                    const data = await fetchPreview(fileObj, newSheet);
                    setFileInfo(data);
                    onLoaded?.(data, fileObj, { sheet_name: newSheet, sheets: data?.sheets ?? [] });
                  } catch (err) {
                    setError(err?.response?.data?.detail || "Sheet preview failed");
                  } finally {
                    setLoading(false);
                  }
                }}
                style={{ width: "100%", padding: 8, borderRadius: 8, border: "1px solid #d1d5db" }}
              >
                {fileInfo.sheets.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          )}

          {showPreview && <PreviewTable data={fileInfo} />}

        </div>
      )}
    </div>
  );
}

export default FileUploadCard;

