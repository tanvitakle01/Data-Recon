import { useNavigate } from "react-router-dom";
import { Badge } from "@bristlecone/canopy";
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

// One resolved side of the mapping (source or target). Shows the connector, its
// acquisition mode, and the columns brought in for comparison (excluding the
// MDT/recommended supporting fields, which are tracked but not compared).
function CardSide({ title, role, roleState, onEdit }) {
  const kind = roleState?.kind;
  const dataset = roleState?.dataset;
  const columns = dataset?.columns ?? [];
  const mdt = new Set(dataset?.mdtFields ?? []);
  const compareCols = columns.filter((c) => !mdt.has(c));

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
          {compareCols.length} field{compareCols.length === 1 ? "" : "s"}
          {compareCols.length > 0 && `: ${compareCols.slice(0, 10).join(", ")}`}
          {compareCols.length > 10 ? ` +${compareCols.length - 10} more` : ""}
          {mdt.size > 0 && (
            <span className="wizard-mapcard__mdt"> ({mdt.size} supporting)</span>
          )}
        </p>
      ) : (
        <p className="wizard-mapcard__fields wizard-mapcard__fields--empty">
          No dataset yet — pick a connector on the {title} step.
        </p>
      )}
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
        <div className="wizard-mapcard__notice">
          <span>⚠️ {notice}</span>
          <button
            type="button"
            className="wizard-link"
            onClick={() => dispatch({ type: WizardActions.CLEAR_FIELD_CHANGE_NOTICE })}
          >
            Dismiss
          </button>
        </div>
      )}

      <CardSide title="Source" role="source" roleState={state.source} onEdit={editRole} />
      <CardSide title="Target" role="target" roleState={state.target} onEdit={editRole} />
    </section>
  );
}

export default MappingCard;
