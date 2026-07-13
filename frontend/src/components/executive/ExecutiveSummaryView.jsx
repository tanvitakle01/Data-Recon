import OverallAssessmentCard from "./OverallAssessmentCard";
import ExecutiveBriefCard from "./ExecutiveBriefCard";
import TopRootCausesCard from "./TopRootCausesCard";
import RecommendedActionsCard from "./RecommendedActionsCard";

/**
 * Executive Summary tab — Data → Insights → Executive Narrative → Action,
 * built from the same `cockpit` payload Detailed Insights (CommandCenter)
 * reads, so the two views can never disagree on a number. No drill-down
 * workspace here by design; that stays in Detailed Insights.
 */
export default function ExecutiveSummaryView({ payload }) {
  const cockpit = payload?.cockpit;
  if (!cockpit?.situationRoom) return null;

  return (
    <div className="space-y-6">
      <OverallAssessmentCard situationRoom={cockpit.situationRoom} />
      <ExecutiveBriefCard bullets={cockpit.executiveBriefBullets} />
      <TopRootCausesCard rootCauseExplorer={cockpit.rootCauseExplorer} />
      <RecommendedActionsCard actionCenter={cockpit.actionCenter} />
    </div>
  );
}
