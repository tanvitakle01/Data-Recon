import { CockpitFilterProvider } from "./CockpitFilterContext";
import CommandCenterHero from "./CommandCenterHero";
import ExceptionCompositionPanel from "./ExceptionCompositionPanel";
import RootCauseBoard from "./RootCauseBoard";
import ActionRoadmap from "./ActionRoadmap";

/**
 * Enterprise Reconciliation Command Center — the decision workflow an
 * executive walks through top to bottom:
 *   1. Overall health & trust (hero)          -> can I trust this?
 *   2. What's broken                          -> what dominates?
 *   3. Why it happened                        -> leading cause?
 *   4. What to do next                        -> the actual plan
 *
 * Each section renders nothing when it has no signal — the page compresses
 * instead of showing empty placeholder cards.
 */
export default function CommandCenter({ payload }) {
  const cockpit = payload?.cockpit;
  if (!cockpit?.situationRoom) return null;

  return (
    <CockpitFilterProvider>
      <div className="space-y-6">
        <CommandCenterHero situationRoom={cockpit.situationRoom} executiveBrief={cockpit.executiveBrief} />
        <ExceptionCompositionPanel exceptionLandscape={cockpit.exceptionLandscape} trend={payload?.charts?.trend} />
        <RootCauseBoard rootCauseExplorer={cockpit.rootCauseExplorer} patternIntelligence={cockpit.patternIntelligence} />
        <ActionRoadmap actionCenter={cockpit.actionCenter} />
      </div>
    </CockpitFilterProvider>
  );
}
