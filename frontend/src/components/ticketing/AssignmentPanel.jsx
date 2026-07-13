import { useMemo, useState } from "react";
import { FiX, FiCheck, FiClock } from "react-icons/fi";
import { useTicketing } from "../../ticketing/useTicketing";
import { membersForTeam } from "../../ticketing/teamDirectory";
import { routeRootCause } from "../../ticketing/routingRules";

const AVAILABILITY_TONE = {
  Available: "text-emerald-600",
  Busy: "text-amber-600",
  "Out of Office": "text-slate-400",
};

/**
 * Manual + Auto assignment modal. Manual mode reads team/member options
 * only from context state (`teams`/`members`, themselves seeded from
 * `teamDirectory.js` but editable via the Teams &amp; Members UI); Auto mode
 * reads its recommendation only from `getRecommendation` (assignmentEngine)
 * — this component contains no routing or scoring logic of its own.
 */
export default function AssignmentPanel({ ticket, onClose, onManualAssign, onAutoAssign }) {
  const { teams, members, routingRules, getRecommendation } = useTicketing();
  const [mode, setMode] = useState("manual");
  const defaultTeamKey = ticket.team?.key || routeRootCause(routingRules, ticket.rootCause).teamKey;
  const [teamKey, setTeamKey] = useState(defaultTeamKey);
  const [memberId, setMemberId] = useState(ticket.assignee?.id || "");
  const [confirmation, setConfirmation] = useState(null); // null | "sending" | "sent"

  const teamMembers = membersForTeam(members, teamKey);
  const recommendation = useMemo(() => getRecommendation(ticket.rootCause), [getRecommendation, ticket.rootCause]);

  const finishWithConfirmation = () => {
    setConfirmation("sending");
    window.setTimeout(() => setConfirmation("sent"), 300);
    window.setTimeout(onClose, 1300);
  };

  const handleManualAssign = () => {
    const isOverride = Boolean(recommendation) && recommendation.member.id !== memberId;
    onManualAssign(teamKey, memberId, isOverride, recommendation?.member?.name);
    finishWithConfirmation();
  };

  const handleAutoAssign = () => {
    onAutoAssign();
    finishWithConfirmation();
  };

  if (confirmation) {
    return (
      <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
        <div className="w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-2xl">
          {confirmation === "sending" ? (
            <>
              <FiClock className="mx-auto mb-3 animate-pulse text-slate-400" size={28} />
              <div className="text-sm font-extrabold text-slate-600">Assigning &amp; sending notification…</div>
            </>
          ) : (
            <>
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50">
                <FiCheck className="text-emerald-600" size={24} />
              </div>
              <div className="text-sm font-extrabold text-slate-900">Assigned</div>
              <div className="mt-1 text-xs font-bold text-emerald-600">Email Sent ✓</div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-[11px] font-black uppercase tracking-widest text-slate-400">{ticket.id}</div>
            <h3 className="m-0 text-lg font-extrabold text-slate-900">{ticket.title}</h3>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <FiX size={18} />
          </button>
        </div>

        <div className="mb-5 flex gap-1 rounded-full bg-slate-100 p-1">
          {["manual", "auto"].map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`flex-1 rounded-full py-1.5 text-xs font-extrabold capitalize transition-colors ${
                mode === m ? "bg-white text-slate-900 shadow" : "text-slate-500"
              }`}
            >
              {m} Assignment
            </button>
          ))}
        </div>

        {mode === "manual" ? (
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-bold text-slate-500">Team</label>
              <select
                value={teamKey}
                onChange={(e) => {
                  setTeamKey(e.target.value);
                  setMemberId("");
                }}
                className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-800"
              >
                {teams.map((team) => (
                  <option key={team.key} value={team.key}>
                    {team.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-bold text-slate-500">Eligible Team Members</label>
              <div className="space-y-1.5">
                {teamMembers.map((member) => (
                  <label
                    key={member.id}
                    className={`flex cursor-pointer items-center justify-between rounded-xl border px-3 py-2 text-sm font-semibold transition-colors ${
                      memberId === member.id ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span>
                      {member.name}
                      <span className="ml-1.5 text-xs font-medium text-slate-400">{member.specialty}</span>
                      <span className={`ml-1.5 text-xs font-bold ${AVAILABILITY_TONE[member.availability] || "text-slate-400"}`}>
                        · {member.availability}
                      </span>
                    </span>
                    <input
                      type="radio"
                      name="member"
                      className="h-4 w-4"
                      checked={memberId === member.id}
                      onChange={() => setMemberId(member.id)}
                    />
                  </label>
                ))}
                {teamMembers.length === 0 ? <div className="text-xs font-semibold text-slate-400">No members on this team yet.</div> : null}
              </div>
              {recommendation && memberId && memberId !== recommendation.member.id ? (
                <div className="mt-2 text-[11px] font-bold text-amber-600">
                  Overriding recommended assignee: {recommendation.member.name}.
                </div>
              ) : null}
            </div>

            <button
              type="button"
              disabled={!memberId}
              onClick={handleManualAssign}
              className="w-full rounded-xl bg-slate-900 py-2.5 text-sm font-extrabold text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
            >
              Assign
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {recommendation ? (
              <>
                <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
                  <div className="text-[11px] font-black uppercase tracking-wide text-blue-500">Recommended Assignee</div>
                  <div className="mb-2 text-lg font-black text-slate-900">{recommendation.member.name}</div>
                  <div className="text-[11px] font-black uppercase tracking-wide text-blue-500">Reason</div>
                  <ul className="m-0 list-none space-y-1 p-0">
                    {recommendation.reasons.map((reason) => (
                      <li key={reason} className="text-xs font-semibold text-slate-700">
                        {reason}
                      </li>
                    ))}
                  </ul>
                </div>
                <button
                  type="button"
                  onClick={handleAutoAssign}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-2.5 text-sm font-extrabold text-white hover:bg-emerald-700"
                >
                  <FiCheck /> Auto Assign
                </button>
              </>
            ) : (
              <div className="text-sm font-semibold text-slate-500">No eligible (available) team member found for this root cause.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
