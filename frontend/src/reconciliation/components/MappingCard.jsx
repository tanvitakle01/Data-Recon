import { useNavigate } from "react-router-dom";
import { Badge, Alert } from "@bristlecone/canopy";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";

// Acquisition mode label for a connector kind — live systems fetch, files upload.
const MODE = {
  excel: "File Upload",
  csv: "File Upload",
  s4: "Live Fetch",
  ibp: "Live Fetch",
  ecc: "Live Fetch",
  bw: "Live Fetch",
};

// One resolved side of the mapping (source or target). Shows the connector,
// its acquisition mode, and the columns brought in for comparison.
function CardSide({ title, role, roleState, onEdit }) {
  const kind = roleState?.kind;
  const dataset = roleState?.dataset;
  const columns = dataset?.columns ?? [];

  return (
    <div className="wizard-mapcard__side">
      <div className="wizard-mapcard__side-head">
        <span className="wizard-mapcard__side-title">{title}</span>
        {kind ? (
          <Badge variant="success" dot>
            {dataset?.filename ?? kind}
          </Badge>
        ) : (
          <Badge variant="warning">Not selected</Badge>
        )}
        {kind && MODE[kind] && (
          <span className="wizard-mapcard__mode">· {MODE[kind]}</span>
        )}
        <span className="wizard-mapcard__spacer" />
        <button type="button" className="wizard-link" onClick={() => onEdit(role)}>
          Edit fields →
        </button>
      </div>
      {dataset ? (
        <p className="wizard-mapcard__fields">
          {columns.length} field{columns.length === 1 ? "" : "s"}
          {columns.length > 0 && `: ${columns.slice(0, 10).join(", ")}`}
          {columns.length > 10 ? ` +${columns.length - 10} more` : ""}
        </p>
      ) : (
        <p className="wizard-mapcard__fields wizard-mapcard__fields--empty">
          No dataset yet — pick a connector on the {title} step.
        </p>
      )}
    </div>
  );
}

// One resolved operation, formatted for a quick scan: op name, the field it
// acts on, and its key parameters — never the raw mapping-sheet metadata or
// the AI's intermediate reasoning (relevant/enriched fields, the chain) that
// produced it; those stay in wizard state for the Transformations Editor only.
function operationSummary(op) {
  const params = op.params && Object.keys(op.params).length > 0 ? JSON.stringify(op.params) : null;
  return [op.op, op.field ? `on ${op.field}` : null, params].filter(Boolean).join(" ");
}

// The final, ordered set of deterministic operations the AI mapping-resolution
// chain produced from the mapping sheet (see TransformationSpecStep's
// runMappingResolution) — shown here, and nowhere else, as the Mapping Card's
// resolved-transformation summary. Absent until a mapping sheet has been
// resolved against both datasets; the Transformations Editor is still the place to
// edit these steps.
function ResolvedOperations({ mappingResolution }) {
  const operations = mappingResolution?.operations ?? [];
  if (!mappingResolution || operations.length === 0) return null;

  return (
    <div className="wizard-mapcard__resolution">
      <p className="wizard-mapcard__side-title">Resolved transformation steps</p>
      <ol className="wizard-mapcard__ops">
        {operations.map((op, idx) => (
          <li key={`${op.op}-${idx}`}>{operationSummary(op)}</li>
        ))}
      </ol>
    </div>
  );
}

// Persistent at-a-glance summary of the resolved mapping, anchored at
// #mapping-card (linked from the sidebar). Jumping back to Step 2/3 to change
// a field selection re-derives only the field-dependent artifacts; typed rules
// survive, and anything genuinely invalidated is surfaced via fieldChangeNotice
// rather than silently dropped.
function MappingCard() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const notice = state.transformationSpec?.fieldChangeNotice;
  const mappingResolution = state.transformationSpec?.mappingResolution;

  const editRole = (role) => {
    if (state.stepStatus[role] === "locked") return;
    dispatch({ type: WizardActions.GO_TO_STEP, step: role });
    navigate(`/reconciliation/${role}`);
  };

  return (
    <section id="mapping-card" className="wizard-section wizard-mapcard">
      <div className="wizard-mapcard__head">
        <h3 className="wizard-section__title">Mapping Card</h3>
        <span className="wizard-mapcard__hint">Current resolved mapping</span>
      </div>

      {notice && (
        <Alert
          variant="warning"
          onDismiss={() => dispatch({ type: WizardActions.CLEAR_FIELD_CHANGE_NOTICE })}
          style={{ marginBottom: 12 }}
        >
          {notice}
        </Alert>
      )}

      <CardSide title="Source" role="source" roleState={state.source} onEdit={editRole} />
      <CardSide title="Target" role="target" roleState={state.target} onEdit={editRole} />
      <ResolvedOperations mappingResolution={mappingResolution} />
    </section>
  );
}

export default MappingCard;
