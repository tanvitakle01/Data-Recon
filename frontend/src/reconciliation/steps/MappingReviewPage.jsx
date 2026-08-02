// Standalone route wrapper around MappingReviewBody, kept for deep-linking —
// reached from the Mapping step's "Open mapping review" button/link on
// /reconciliation/transformation-spec/mapping-review. NOT one of the 5
// numbered wizard steps: it never touches state.step, so the stepper keeps
// showing Step 4 "Mapping" as current throughout.
//
// The merged Mapping step (TransformationSpecStep) also renders
// MappingReviewBody inline, as a collapsible full-page card, so the actual
// KPI/search/table content lives there — this file is just the page chrome
// (header + "Back to Mapping" footer) around it.
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { Button } from "@bristlecone/canopy";
import MappingReviewBody from "../components/MappingReviewBody";

function MappingReviewPage() {
  const { state } = useWizard();
  const navigate = useNavigate();
  const { valueMappings } = state.transformationSpec;

  const backToMapping = () => navigate("/reconciliation/transformation-spec");

  return (
    <section className="wizard-step wizard-step--canvas">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">Mapping — Mapping Review</p>
        <h2 className="wizard-step__title">Mapping Review</h2>
        <p className="wizard-step__desc">
          {valueMappings
            ? 'Review this run\'s value-pairing results. A freshly-verified pairing is applied to this run and persisted to the value-pair library automatically, so future runs reuse it with no LLM call.'
            : "Run AI-mapping on the Mapping step first."}
        </p>
      </header>

      <div className="wizard-step__body">
        <MappingReviewBody />
      </div>

      <footer className="wizard-step__footer">
        <Button type="button" variant="outline" onClick={backToMapping}>
          Back to Mapping
        </Button>
      </footer>
    </section>
  );
}

export default MappingReviewPage;
