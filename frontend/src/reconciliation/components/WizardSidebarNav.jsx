import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  FiGrid,
  FiDownload,
  FiUpload,
  FiGitMerge,
  FiCheckCircle,
  FiColumns,
  FiList,
  FiEye,
} from "react-icons/fi";
import { Tooltip, Badge } from "@bristlecone/canopy";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getVisibleSteps } from "../steps/stepConfig";

// Icon per step key — used for the collapsed icon rail and as a small glyph
// hint in the expanded list.
const STEP_ICON = {
  comparisonType: FiGrid,
  source: FiDownload,
  target: FiUpload,
  transformationSpec: FiGitMerge,
  reconciliation: FiCheckCircle,
};

// Human label + acquisition mode for a connector kind. Live systems fetch;
// files are uploaded.
function connectorSummary(role) {
  if (!role || !role.kind) return null;
  const map = {
    excel: { label: "Excel", mode: "File Upload" },
    csv: { label: "CSV", mode: "File Upload" },
    s4: { label: "S/4HANA", mode: "Live Fetch" },
    ibp: { label: "SAP IBP", mode: "Live Fetch" },
    ecc: { label: "SAP ECC", mode: "Live Fetch" },
    bw: { label: "SAP BW", mode: "Live Fetch" },
  };
  return map[role.kind] ?? { label: role.kind, mode: null };
}

// Approval state across the three flows (Manual contract / Deterministic
// contract / script approval). Returns null when nothing is approved yet.
function approvalSummary(spec) {
  if (!spec) return null;
  if (spec.contract) {
    return { label: "Approved", detail: `v${spec.contract.contract_version ?? 1}` };
  }
  if (spec.deterministicContract) return { label: "Approved", detail: "AI-mapping" };
  if (spec.scriptApproval) return { label: "Approved", detail: "transformation" };
  return null;
}

function StepMarker({ status, index }) {
  const glyph = status === "complete" ? "✓" : index + 1;
  return <span className="wsb-step__mk">{glyph}</span>;
}

function WizardSidebarNav({ collapsed }) {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const steps = getVisibleSteps(state.transformationSpec?.useScriptTransformations);
  const spec = state.transformationSpec;

  const jumpToStep = (step) => {
    if (state.stepStatus[step.key] === "locked") return;
    dispatch({ type: WizardActions.GO_TO_STEP, step: step.key });
    navigate(`/reconciliation/${step.path}`);
  };

  const contextRows = useMemo(() => {
    const rows = [];
    if (state.comparisonType) rows.push({ k: "Type", v: state.comparisonType.label });
    const src = connectorSummary(state.source);
    if (src) rows.push({ k: "Source", v: src.label, mode: src.mode });
    const tgt = connectorSummary(state.target);
    if (tgt) rows.push({ k: "Target", v: tgt.label, mode: tgt.mode });
    const appr = approvalSummary(spec);
    if (appr) rows.push({ k: "Contract", v: appr.label, badge: true, mono: appr.detail });
    return rows;
  }, [state.comparisonType, state.source, state.target, spec]);

  // Quick links appear ONLY once their target exists.
  const quickLinks = useMemo(() => {
    const links = [];
    // The Mapping Card is always rendered on the Transformation Spec step, so
    // surface its jump-link as soon as either side has a dataset to summarize.
    if (spec?.mapping || state.source?.dataset || state.target?.dataset) {
      links.push({
        id: "mapping-card",
        label: "Mapping Card",
        icon: FiColumns,
        to: "/reconciliation/transformation-spec#mapping-card",
      });
    }
    if (spec?.valueMappings) {
      links.push({
        id: "mapping-review",
        label: "View Mapping Review",
        icon: FiList,
        to: "/reconciliation/transformation-spec/mapping-review",
      });
    }
    if (spec?.contract || spec?.scriptApproval) {
      links.push({
        id: "transformation-preview",
        label: "Review Transformation Preview",
        icon: FiEye,
        to: "/reconciliation/transformation-spec#transformation-preview",
      });
    }
    return links;
  }, [spec, state.source?.dataset, state.target?.dataset]);

  return (
    <div className={`wsb ${collapsed ? "wsb--collapsed" : ""}`}>
      <p className="wsb__label">Steps</p>
      <ul className="wsb__steps">
        {steps.map((step, idx) => {
          const status = state.stepStatus[step.key];
          const isActive = state.step === step.key;
          const Icon = STEP_ICON[step.key] ?? FiGrid;
          return (
            <li key={step.key}>
              <Tooltip content={collapsed ? `${idx + 1}. ${step.label}` : null} side="right">
                <button
                  type="button"
                  className={`wsb-step is-${status} ${isActive ? "is-active" : ""}`}
                  onClick={() => jumpToStep(step)}
                  disabled={status === "locked"}
                  aria-current={isActive ? "step" : undefined}
                >
                  {collapsed ? (
                    status === "complete" ? (
                      <span className="wsb-step__mk">✓</span>
                    ) : (
                      <span className="wsb-step__mk">{idx + 1}</span>
                    )
                  ) : (
                    <StepMarker status={status} index={idx} />
                  )}
                  <span className="wsb-step__label">{step.label}</span>
                  {!collapsed && <Icon className="wsb-step__glyph" aria-hidden="true" />}
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ul>

      {contextRows.length > 0 && !collapsed && (
        <>
          <p className="wsb__label">Context</p>
          <dl className="wsb-ctx">
            {contextRows.map((row) => (
              <div className="wsb-ctx__row" key={row.k}>
                <dt className="wsb-ctx__k">{row.k}</dt>
                <dd className="wsb-ctx__v">
                  {row.badge ? (
                    <Badge variant="success" dot>
                      {row.v}
                    </Badge>
                  ) : (
                    row.v
                  )}
                  {row.mode && <span className="wsb-ctx__mode"> · {row.mode}</span>}
                  {row.mono && <span className="wsb-ctx__mono"> {row.mono}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}

      {quickLinks.length > 0 && (
        <>
          {!collapsed && <p className="wsb__label">Jump to</p>}
          {collapsed && <div className="wsb__rail-div" />}
          <ul className="wsb__links">
            {quickLinks.map((link) => {
              const Icon = link.icon;
              return (
                <li key={link.id}>
                  <Tooltip content={collapsed ? link.label : null} side="right">
                    <button
                      type="button"
                      className="wsb-link"
                      onClick={() => navigate(link.to)}
                    >
                      <Icon className="wsb-link__ic" aria-hidden="true" />
                      <span className="wsb-link__label">{link.label}</span>
                    </button>
                  </Tooltip>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

export default WizardSidebarNav;
