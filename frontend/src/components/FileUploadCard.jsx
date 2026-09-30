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
        border: "1px solid var(--border)",
        padding: 16,
        borderRadius: 14,
        background: "var(--surface)",
      }}
    >
      <h3 style={{ marginTop: 0, fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>{title}</h3>


      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        style={{
          border: `1.5px dashed ${dragOver ? "var(--accent)" : "var(--border-strong)"}`,
          borderRadius: 10,
          padding: 16,
          textAlign: "center",
          cursor: "pointer",
          background: dragOver ? "var(--accent-tint)" : "transparent",
        }}
      >
        <div style={{ fontSize: 13, color: "var(--ink-2)", fontWeight: 600 }}>
          Drag &amp; drop a file here, or click to choose
        </div>
        <div style={{ fontSize: 12, color: "var(--muted-2)", marginTop: 2 }}>Accepted: .xlsx, .xls, .csv</div>
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
        <div style={{ marginTop: 8, color: "var(--missing)", fontSize: 13 }}>
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
              background: "var(--match-bg)",
              color: "var(--match)",
              fontWeight: 800,
              fontSize: 12,
            }}
          >
            ✓ {fileInfo.filename}
          </div>
          <div style={{ marginTop: 6, color: "var(--muted)", fontWeight: 600, fontSize: 13 }}>
            {fileInfo.rows} rows × {fileInfo.cols} cols
          </div>

          <button className="btn-secondary" style={{ marginTop: 10 }} onClick={() => setShowPreview((s) => !s)}>
            {showPreview ? "Hide Preview" : "Preview"}
          </button>


          {fileInfo?.sheets?.length > 1 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Sheet</div>
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
                style={{ width: "100%", padding: 8, borderRadius: 8, border: "1px solid var(--border-strong)", background: "var(--surface)", color: "var(--ink)" }}
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

