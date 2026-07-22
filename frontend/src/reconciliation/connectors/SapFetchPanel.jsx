import { useState } from "react";
import api from "../../services/api";
import PreviewTable from "../../components/PreviewTable";
import { Button } from "@bristlecone/canopy";

const SYSTEMS = {
  s4: {
    label: "SAP S/4HANA",
    endpoint: "/api/s4/test-preview",
    fallbackColumns: ["Material", "Plnt", "ReqDlvDate", "ReqDlvQty"],
  },
  ibp: {
    label: "SAP IBP",
    endpoint: "/api/ibp/test-preview",
    fallbackColumns: ["LOCID", "PRDID", "SALESORDERREQUEST", "KEYFIGUREDATE"],
  },
};

// Connects to a live SAP system through the existing test-preview endpoints
// and hands the fetched rows back up so the wizard treats them exactly like
// an uploaded dataset.
function SapFetchPanel({ system, dataset, onLoaded }) {
  const config = SYSTEMS[system];
  const [status, setStatus] = useState(dataset ? "connected" : "idle"); // idle | connecting | connected | error
  const [error, setError] = useState(null);
  const [showPreview, setShowPreview] = useState(false);

  const fetchData = async () => {
    setStatus("connecting");
    setError(null);
    try {
      const res = await api.get(config.endpoint);
      const payload = res.data ?? {};

      if (!payload.success) {
        setStatus("error");
        setError(payload.error || `${config.label} connection failed.`);
        return;
      }

      const data = Array.isArray(payload.data) ? payload.data : [];
      const columns = data.length ? Object.keys(data[0]) : config.fallbackColumns;
      const preview = data.slice(0, 10);

      setStatus("connected");
      onLoaded({
        columns,
        preview,
        rows: data,
        rowCount: data.length,
      });
    } catch (err) {
      setStatus("error");
      setError(err?.response?.data?.error || err?.message || `${config.label} fetch failed.`);
    }
  };

  return (
    <div className="wizard-connector-panel">
      <div className="sap-fetch">
        <div className="sap-fetch__row">
          <Button
            type="button"
            variant="primary"
            onClick={fetchData}
            disabled={status === "connecting"}
          >
            {status === "connecting"
              ? `Connecting to ${config.label}…`
              : dataset
                ? `Re-fetch from ${config.label}`
                : `Fetch from ${config.label}`}
          </Button>

          <span className={`sap-fetch__status is-${status}`}>
            {status === "idle" && "Not connected"}
            {status === "connecting" && "Connecting…"}
            {status === "connected" && `Connected · ${dataset?.rowCount ?? 0} rows`}
            {status === "error" && "Connection failed"}
          </span>
        </div>

        {error && <p className="wizard-step__error">{error}</p>}

        {dataset && (
          <div className="sap-fetch__preview">
            <Button
              type="button"
              variant="outline"
              onClick={() => setShowPreview((s) => !s)}
            >
              {showPreview ? "Hide preview" : "Preview data"}
            </Button>
            {showPreview && (
              <PreviewTable
                data={{ columns: dataset.columns, preview: dataset.preview }}
                title={`${config.label} preview (first 10 rows)`}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default SapFetchPanel;
