// Dataset Detail Preview — a dedicated page (its own route) reached from the
// "Open Detailed Preview" button on a connector's Build Dataset card. It reads
// the already-imported dataset straight from wizard state, so navigating here
// and back never re-fetches or loses import state. Kept off the main flow so
// the (potentially large) data grid isn't rendered until the user asks for it.
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@bristlecone/canopy";
import { useWizard } from "../context/useWizard";
import AuxiliaryFieldsPanel from "../components/AuxiliaryFieldsPanel";
import { exportDatasetToCsv } from "../../utils/csvExport";

const DEFAULT_COL_WIDTH = 150;

function looksNumeric(v) {
  if (v == null || v === "") return false;
  return !Number.isNaN(Number(String(v).replace(/,/g, "")));
}

function DatasetDetailPreviewPage() {
  const { role } = useParams();
  const navigate = useNavigate();
  const { state } = useWizard();
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  const roleState = role === "source" || role === "target" ? state[role] : null;
  const dataset = roleState?.dataset ?? null;
  const roleLabel = role === "source" ? "Source" : "Target";

  const backToConnector = () => navigate(`/reconciliation/${role}`);

  const columns = dataset?.columns ?? [];
  const rows = dataset?.preview ?? [];
  const fullRows = dataset?.rows ?? null;

  const downloadDataset = async () => {
    if (!fullRows?.length) return;
    setDownloadError(null);
    setDownloading(true);
    try {
      await exportDatasetToCsv({
        sourceSystem: dataset?.kind === "s4" ? "S4" : dataset?.kind === "ibp" ? "IBP" : roleLabel,
        datasetName: dataset?.filename || `${roleLabel} dataset`,
        columns,
        rows: fullRows,
      });
    } catch (err) {
      setDownloadError(`Failed to export dataset: ${err?.message || err}`);
    } finally {
      setDownloading(false);
    }
  };

  if (!dataset) {
    return (
      <section className="wizard-step">
        <header className="wizard-step__header">
          <p className="wizard-step__eyebrow">{roleLabel} — Detailed Preview</p>
          <h2 className="wizard-step__title">Imported Dataset Preview</h2>
          <p className="wizard-step__desc">No dataset has been imported for this side yet.</p>
        </header>
        <div className="wizard-step__body">
          <p className="wizard-field__help">
            Build and import a dataset first, then open its detailed preview.
          </p>
        </div>
        <footer className="wizard-step__footer">
          <Button type="button" variant="outline" onClick={backToConnector}>
            Back
          </Button>
        </footer>
      </section>
    );
  }

  return (
    <section className="wizard-step">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">{roleLabel} — Detailed Preview</p>
        <h2 className="wizard-step__title">Imported Dataset Preview</h2>
        <p className="wizard-step__desc">
          {(dataset.rowCount ?? 0).toLocaleString()} rows · {columns.length} columns
        </p>
      </header>

      <div className="wizard-step__body">
        <section className="ibpw-panel ibpw-imported">
          <header className="ibpw-panel__head">
            <h4 className="ibpw-panel__title">Imported Dataset Preview</h4>
            <span className="ibpw-spacer" />
            <span className="ibpw-badge ibpw-badge--accent">
              {(dataset.rowCount ?? 0).toLocaleString()} rows
            </span>
            <span className="ibpw-badge ibpw-badge--count">{columns.length} cols</span>
            <button
              type="button"
              className="ibpw-btn ibpw-btn--ghost ibpw-btn--header"
              onClick={downloadDataset}
              disabled={downloading || !fullRows?.length}
            >
              {downloading && <span className="ibpw-btn__spin" />}
              {downloading ? "Preparing…" : "Download Data"}
            </button>
          </header>
          {downloadError && <p className="ibpw-summary__error">⚠️ {downloadError}</p>}

          {rows.length > 0 ? (
            <>
              <div className="ibpw-grid-wrap">
                <table className="ibpw-grid">
                  <colgroup>
                    {columns.map((c) => (
                      <col key={c} style={{ width: DEFAULT_COL_WIDTH }} />
                    ))}
                  </colgroup>
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th key={c} style={{ position: "sticky" }}>
                          <div className="ibpw-grid__th-inner">
                            <span className="ibpw-grid__th-label" title={c}>
                              {c}
                            </span>
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, idx) => (
                      <tr key={idx}>
                        {columns.map((c) => (
                          <td
                            key={c}
                            className={looksNumeric(row[c]) ? "ibpw-grid__num" : ""}
                            title={row[c] != null ? String(row[c]) : ""}
                          >
                            {row[c] != null ? String(row[c]) : ""}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="ibpw-imported__caption">
                Showing {rows.length} of {(dataset.rowCount ?? 0).toLocaleString()} rows
              </p>
            </>
          ) : (
            <p className="ibpw-imported__caption">No preview rows available for this dataset.</p>
          )}
        </section>

        <AuxiliaryFieldsPanel auxiliaryFields={dataset.auxiliaryFields} />
      </div>

      <footer className="wizard-step__footer">
        <Button type="button" variant="outline" onClick={backToConnector}>
          Back
        </Button>
      </footer>
    </section>
  );
}

export default DatasetDetailPreviewPage;
