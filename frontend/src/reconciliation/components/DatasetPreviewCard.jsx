import { Button, Badge } from "@bristlecone/canopy";
import { FileSpreadsheet } from "lucide-react";

// Flow A (Excel/CSV) "Dataset Preview" — the second and final card of the
// file-upload path. Purely a presentation of the dataset already sitting in
// wizard state; it fetches nothing and owns no state itself. Two separate
// cards (dataset summary, dataset preview) rather than one scrolling panel —
// the preview table renders at its natural height (the backend already caps
// `preview` to a small row count, so there's nothing to clip).
function fileTypeFromName(filename) {
  const ext = (filename || "").split(".").pop()?.toLowerCase();
  if (ext === "xlsx" || ext === "xls") return "Excel";
  if (ext === "csv") return "CSV";
  return ext ? ext.toUpperCase() : "—";
}

function DatasetPreviewCard({ dataset, onReplaceFile }) {
  if (!dataset) return null;

  const columns = dataset.columns ?? [];
  const previewRows = dataset.preview ?? [];

  return (
    <div className="ct-col">
      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Dataset</h3>
          <span className="ct-card__spacer" />
          <Badge variant="success" dot>
            Imported
          </Badge>
        </div>
        <div className="ct-card__body">
          <div className="ct-file-row">
            <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
            <span className="ct-file-row__name" title={dataset.filename}>
              {dataset.filename}
            </span>
            <span className="ct-file-row__meta mono">
              {fileTypeFromName(dataset.filename)} · {dataset.rowCount} rows · {dataset.colCount} columns
            </span>
            <span className="ct-card__spacer" />
            <Button type="button" variant="outline" size="sm" onClick={onReplaceFile}>
              Replace File
            </Button>
          </div>
        </div>
      </section>

      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Dataset preview</h3>
          <span className="ct-card__spacer" />
          <span className="ct-card__hint">
            First {previewRows.length} of {dataset.rowCount} rows
          </span>
        </div>
        <div className="ct-card__body ct-card__body--flush ct-table-wrap">
          <table className="ct-table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewRows.map((row, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col} className="mono">
                      {row[col]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default DatasetPreviewCard;
