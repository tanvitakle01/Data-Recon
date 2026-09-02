import { useState } from "react";
import { LayoutDashboard, GitCompareArrows, Blocks, Table2, Wand2, Eye, Home } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { ComponentGallery } from "./screens/ComponentGallery";
import { MappingScreen } from "./screens/MappingScreen";
import { TypeScreen } from "./screens/TypeScreen";
import { ConnectorScreen } from "./screens/ConnectorScreen";
import { ResultsScreen } from "./screens/ResultsScreen";
import { MappingReviewScreen } from "./screens/MappingReviewScreen";
import { TransformationPreviewScreen } from "./screens/TransformationPreviewScreen";
import { DashboardScreen } from "./screens/DashboardScreen";
import { LandingScreen } from "./screens/LandingScreen";

const NAV = [
  { key: "landing", label: "Landing page", icon: <Home className="h-[18px] w-[18px]" /> },
  { key: "dashboard", label: "Dashboard", icon: <LayoutDashboard className="h-[18px] w-[18px]" /> },
  { key: "reconciliation", label: "Reconciliation Engine", icon: <GitCompareArrows className="h-[18px] w-[18px]" /> },
  { key: "components", label: "Component Library", icon: <Blocks className="h-[18px] w-[18px]" /> },
];

const ORDER = ["type", "source", "target", "mapping", "results"];
const WIZARD_STATUS = { type: "complete", source: "complete", target: "complete", mapping: "current", results: "locked" };
const WIZARD_META = [
  { key: "type", label: "Type", caption: "Sales Order History" },
  { key: "source", label: "Source", caption: "SAP S/4HANA" },
  { key: "target", label: "Target", caption: "SAP IBP" },
  { key: "mapping", label: "Mapping", caption: "Deterministic" },
  { key: "results", label: "Results" },
];

export default function RedesignApp() {
  const [dark, setDark] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [active, setActive] = useState("landing");
  const [wizardStep, setWizardStep] = useState("mapping");

  const currentMain = ["mapping", "mappingReview", "transformPreview"].includes(wizardStep) ? "mapping" : wizardStep;
  const steps = WIZARD_META.map((s) => ({ ...s, status: s.key === currentMain ? "current" : WIZARD_STATUS[s.key] }));

  const goStep = (key) => { setActive("reconciliation"); setWizardStep(key); };
  const prevOf = (k) => ORDER[Math.max(ORDER.indexOf(k) - 1, 0)];

  if (active === "landing") {
    return (
      <div className={`rdx-root ${dark ? "rdx-dark" : ""} h-screen w-full font-sans`}>
        <LandingScreen onEnter={() => setActive("dashboard")} />
      </div>
    );
  }

  return (
    <div className={`rdx-root ${dark ? "rdx-dark" : ""} flex h-screen w-full overflow-hidden font-sans`}>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        nav={NAV}
        active={active}
        onNavClick={(k) => { setActive(k); if (k === "reconciliation") setWizardStep((s) => s || "mapping"); }}
        dark={dark}
        onToggleDark={() => setDark((d) => !d)}
        user={{ initials: "TT", name: "Tanvi Takle", role: "SAP Integration" }}
        wizard={{
          steps,
          onStepClick: (s) => goStep(s.key),
          context: [
            { label: "Type", value: "Sales Order Hist." },
            { label: "Source", value: "S/4HANA" },
            { label: "Target", value: "IBP" },
            { label: "Contract", value: "contract_a1b2c3", mono: true },
          ],
          quickLinks: [
            { label: "Mapping Card", icon: <Table2 className="h-3.5 w-3.5" />, onClick: () => goStep("mapping") },
            { label: "Mapping Review", icon: <Eye className="h-3.5 w-3.5" />, onClick: () => goStep("mappingReview") },
            { label: "Transformation Preview", icon: <Wand2 className="h-3.5 w-3.5" />, onClick: () => goStep("transformPreview") },
          ],
        }}
      />

      <main className="flex min-w-0 flex-1 flex-col bg-bg">
        {active === "dashboard" && <DashboardScreen onNewRun={() => goStep("type")} />}
        {active === "components" && <ComponentGallery />}
        {active === "reconciliation" && (
          <>
            {wizardStep === "type" && <TypeScreen onContinue={() => setWizardStep("source")} />}
            {wizardStep === "source" && <ConnectorScreen role="source" onBack={() => setWizardStep(prevOf("source"))} onContinue={() => setWizardStep("target")} />}
            {wizardStep === "target" && <ConnectorScreen role="target" onBack={() => setWizardStep("source")} onContinue={() => setWizardStep("mapping")} />}
            {wizardStep === "mapping" && <MappingScreen />}
            {wizardStep === "results" && <ResultsScreen onBack={() => setWizardStep("mapping")} />}
            {wizardStep === "mappingReview" && <MappingReviewScreen onBack={() => setWizardStep("mapping")} />}
            {wizardStep === "transformPreview" && <TransformationPreviewScreen onBack={() => setWizardStep("mapping")} />}
          </>
        )}
      </main>
    </div>
  );
}
