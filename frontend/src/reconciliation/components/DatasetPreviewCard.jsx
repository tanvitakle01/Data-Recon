import PreviewTable from "../../components/PreviewTable";
import { Button, Badge } from "@bristlecone/canopy";

// Flow A (Excel/CSV) "Dataset Preview" card — the second and final card of
// the file-upload path. Purely a presentation of the dataset already sitting
// in wizard state; it fetches nothing and owns no state itself.
function fileTypeFromName(filename) {
  const ext = (filename || "").split(".").pop()?.toLowerCase();
  if (ext === "xlsx" || ext === "xls") return "Excel";
  if (ext === "csv") return "CSV";
  return ext ? ext.toUpperCase() : "—";
}

function DatasetPreviewCard({ dataset, onReplaceFile }) {
  if (!dataset) return null;

  return (
    <div className="wizard-preview-card">
      <div className="wizard-preview-card__status">
        <Badge variant="success">✓ Dataset imported</Badge>
        <span className="wizard-preview-card__filename">{dataset.filename}</span>
      </div>

      <div className="wizard-preview-card__stats">
        <div className="wizard-preview-card__stat">
          <span className="wizard-preview-card__stat-label">Rows</span>
          <span className="wizard-preview-card__stat-value">{dataset.rowCount}</span>
        </div>
        <div className="wizard-preview-card__stat">
          <span className="wizard-preview-card__stat-label">Columns</span>
          <span className="wizard-preview-card__stat-value">{dataset.colCount}</span>
        </div>
        <div className="wizard-preview-card__stat">
          <span className="wizard-preview-card__stat-label">File type</span>
          <span className="wizard-preview-card__stat-value">
            {fileTypeFromName(dataset.filename)}
          </span>
        </div>
      </div>

      <PreviewTable
        data={{ columns: dataset.columns, preview: dataset.preview }}
        title="Data preview"
      />

      <Button type="button" variant="outline" className="mt-4" onClick={onReplaceFile}>
        Replace File
      </Button>
    </div>
  );
}

export default DatasetPreviewCard;
