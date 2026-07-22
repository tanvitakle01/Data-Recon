import { useMemo, useRef, useState } from "react";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import { Badge, Select, Button } from "@bristlecone/canopy";

// Only Sales Order History is offered for now. Additional comparison types
// will be added here (or sourced from /api/comparison-types) as their
// transformation logic is built out.
const COMPARISON_TYPES = [{ id: "salesorderhistory", label: "Sales Order History" }];

const SHEET_ACCEPT = ".xlsx,.xls,.csv";

// One resolved side of the sheet identification (source or target). Shows the
// auto-selected connector + the evidence the LLM cited, so the downstream
// Step 2/3 confirmation isn't a blind "trust me". A side with no confident
// match still shows its evidence as a hint.
function IdentifiedSide({ title, side }) {
  if (!side) return null;
  const confident = Boolean(side.kind);
  return (
    <div className="wizard-identify__side">
      <div className="wizard-identify__side-head">
        <span className="wizard-identify__side-title">{title}</span>
        {confident ? (
          <Badge variant="success" dot>
            {side.label}
          </Badge>
        ) : (
          <Badge variant="warning">Not identified</Badge>
        )}
        {side.confidence && confident && (
          <span className="wizard-identify__confidence">{side.confidence} confidence</span>
        )}
      </div>
      {side.evidence && <p className="wizard-identify__evidence">{side.evidence}</p>}
      {side.fields?.length > 0 && (
        <p className="wizard-identify__fields">
          Candidate fields: {side.fields.slice(0, 8).join(", ")}
          {side.fields.length > 8 ? ` +${side.fields.length - 8} more` : ""}
        </p>
      )}
    </div>
  );
}

function ComparisonTypeStep() {
  const { state, dispatch } = useWizard();
  const selectedId = state.comparisonType?.id ?? "";
  const identification = state.sheetIdentification;

  const sheetInputRef = useRef(null);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetError, setSheetError] = useState(null);

  const handleChange = (event) => {
    const id = event.target.value;
    if (!id) {
      dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
      return;
    }
    const option = COMPARISON_TYPES.find((c) => c.id === id);
    dispatch({
      type: WizardActions.SET_COMPARISON_TYPE,
      comparisonType: { id: option.id, label: option.label },
    });
  };

  // Upload → parse (deterministic) → identify (LLM, allow-listed). Both go
  // through the existing endpoints; identification degrades gracefully, so a
  // failure here never blocks the wizard — the user just selects connectors
  // manually on Steps 2/3. The Step 4 mapping-sheet upload is untouched.
  const handleSheetFile = async (file) => {
    if (!file) return;
    setSheetError(null);
    setSheetLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const parseRes = await api.post("/api/recon/mapping-sheet/parse", formData);
      const idRes = await api.post("/api/recon/mapping-sheet/identify", {
        mapping_sheet: parseRes.data,
      });
      dispatch({
        type: WizardActions.SET_SHEET_IDENTIFICATION,
        identification: {
          ...idRes.data,
          sheet: { name: file.name, size: file.size },
          parsed: parseRes.data,
        },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string" ? detail : "Could not read/identify the mapping sheet."
      );
    } finally {
      setSheetLoading(false);
      if (sheetInputRef.current) sheetInputRef.current.value = "";
    }
  };

  const clearSheet = () => {
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    setSheetError(null);
    if (sheetInputRef.current) sheetInputRef.current.value = "";
  };

  const canContinue = useMemo(() => Boolean(state.comparisonType), [state.comparisonType]);

  return (
    <StepShell stepKey="comparisonType" canContinue={canContinue}>
      <div className="wizard-field">
        <label className="wizard-field__label" htmlFor="comparison-type-select">
          Dataset Type
        </label>
        <Select
          id="comparison-type-select"
          value={selectedId}
          onChange={handleChange}
          options={[
            { value: "", label: "Select a dataset type…" },
            ...COMPARISON_TYPES.map((option) => ({ value: option.id, label: option.label })),
          ]}
        />
        <p className="wizard-field__help">
          This selection is carried forward and will drive the transformation rules used for
          reconciliation.
        </p>
      </div>

      {state.comparisonType && (
        <div className="wizard-dataset-summary">
          <Badge variant="success">Selected</Badge>
          <span>{state.comparisonType.label}</span>
        </div>
      )}

      {/* ── Optional: mapping-sheet-driven system identification ── */}
      <div className="wizard-field wizard-identify">
        <label className="wizard-field__label">Mapping Sheet (optional)</label>
        <p className="wizard-field__help">
          Upload the mapping sheet and we'll identify which systems it describes and pre-select
          the connectors and fields on the next steps. You confirm the connector before any live
          fetch.
        </p>

        <input
          ref={sheetInputRef}
          type="file"
          accept={SHEET_ACCEPT}
          style={{ display: "none" }}
          onChange={(e) => handleSheetFile(e.target.files?.[0] ?? null)}
        />

        {!identification ? (
          <Button
            variant="secondary"
            onClick={() => sheetInputRef.current?.click()}
            disabled={sheetLoading}
          >
            {sheetLoading ? "Reading sheet…" : "Upload mapping sheet"}
          </Button>
        ) : (
          <div className="wizard-identify__result">
            <div className="wizard-identify__filebar">
              <span className="wizard-identify__filename">
                {identification.sheet?.name ?? "mapping sheet"}
              </span>
              <button type="button" className="wizard-link" onClick={clearSheet}>
                Remove
              </button>
            </div>

            <IdentifiedSide title="Source system" side={identification.source} />
            <IdentifiedSide title="Target system" side={identification.target} />

            {identification.degraded && identification.degraded_reason && (
              <p className="wizard-identify__warn">⚠️ {identification.degraded_reason}</p>
            )}
            {(identification.warnings ?? []).map((w, i) => (
              <p className="wizard-identify__warn" key={i}>
                ⚠️ {w}
              </p>
            ))}
            {identification.provider && (
              <p className="wizard-identify__provider">Identified via {identification.provider}</p>
            )}
          </div>
        )}

        {sheetError && <p className="wizard-identify__warn">⚠️ {sheetError}</p>}
      </div>
    </StepShell>
  );
}

export default ComparisonTypeStep;
