import { FiPlus, FiTrash2 } from "react-icons/fi";
import { useTicketing } from "../../ticketing/useTicketing";

/**
 * Editable Root Cause -> Team routing table. Every row is stored in
 * TicketingContext's `routingRules` state (seeded from
 * `ticketing/routingRules.js`'s DEFAULT_ROUTING_RULES) — this component
 * never hardcodes a root-cause-to-team decision itself, it only edits the
 * configuration that `routeRootCause()` reads.
 */
export default function RoutingRulesEditor() {
  const { routingRules, teams, addRoutingRule, updateRoutingRule, removeRoutingRule } = useTicketing();

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="m-0 text-2xl font-black tracking-tight text-slate-900">Ticket Routing Rules</h2>
          <div className="mt-1 text-sm font-semibold text-slate-500">
            Configures which team (and required skill) a detected root cause routes to.
          </div>
        </div>
        <button
          type="button"
          onClick={() => addRoutingRule({ rootCause: "", teamKey: teams[0]?.key || "", requiredSkill: "" })}
          disabled={teams.length === 0}
          className="flex items-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-extrabold text-white disabled:cursor-not-allowed disabled:bg-slate-200"
        >
          <FiPlus size={14} /> Add Rule
        </button>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left">
              <th className="px-4 py-3 text-[11px] font-black uppercase tracking-wide text-slate-400">Root Cause</th>
              <th className="px-4 py-3 text-[11px] font-black uppercase tracking-wide text-slate-400">Routes To Team</th>
              <th className="px-4 py-3 text-[11px] font-black uppercase tracking-wide text-slate-400">Required Skill (optional)</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {routingRules.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-xs font-semibold text-slate-400">
                  No routing rules configured. Detected root causes will fall back to the first available team.
                </td>
              </tr>
            ) : (
              routingRules.map((rule) => (
                <tr key={rule.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5">
                    <input
                      type="text"
                      value={rule.rootCause}
                      onChange={(e) => updateRoutingRule(rule.id, { rootCause: e.target.value })}
                      placeholder="Product Mapping Gap"
                      className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-800"
                    />
                  </td>
                  <td className="px-4 py-2.5">
                    <select
                      value={rule.teamKey}
                      onChange={(e) => updateRoutingRule(rule.id, { teamKey: e.target.value })}
                      className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-800"
                    >
                      {teams.map((team) => (
                        <option key={team.key} value={team.key}>
                          {team.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-2.5">
                    <input
                      type="text"
                      value={rule.requiredSkill || ""}
                      onChange={(e) => updateRoutingRule(rule.id, { requiredSkill: e.target.value })}
                      placeholder="Product Mapping"
                      className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-800"
                    />
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => removeRoutingRule(rule.id)}
                      className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-red-50 hover:text-red-600"
                      aria-label="Remove rule"
                    >
                      <FiTrash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
