import { useMemo, useState } from "react";
import api from "../services/api";
import PreviewTable from "./PreviewTable";


function FileUploadCard({
  title,
  accept = ".xlsx,.xls",
  onLoaded,
}) {
  const [fileInfo, setFileInfo] = useState(null);
  const [fileObj, setFileObj] = useState(null);
  const [selectedSheet, setSelectedSheet] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);


  const fetchPreview = async (file, sheetName = null) => {
    const formData = new FormData();
    formData.append("file", file);
    if (sheetName) formData.append("sheet_name", sheetName);

    const response = await api.post("/preview", formData);
    return response.data;
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
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


  return (
    <div className="card" style={{ border: "1px solid #ddd", padding: 16, borderRadius: 10 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>

      <input type="file" accept={accept} onChange={handleUpload} />

      {loading && <div style={{ marginTop: 8 }}>Loading preview…</div>}
      {error && (
        <div style={{ marginTop: 8, color: "#b91c1c", fontSize: 13 }}>
          {error}
        </div>
      )}

      {fileInfo && (
        <div style={{ marginTop: 10 }}>
          <div>✅ {fileInfo.filename}</div>
          <div>
            {fileInfo.rows} rows × {fileInfo.cols} cols
          </div>

          <button style={{ marginTop: 10 }} onClick={() => setShowPreview((s) => !s)}>
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

