import { useCallback, useEffect, useMemo, useState } from "react";
import { reconcileTicketsWithRootCauses, seedDemoTickets } from "./ticketEngine";
import { recommendAssignee } from "./assignmentEngine";
import { findMember, findTeam, DEFAULT_TEAMS, DEFAULT_MEMBERS } from "./teamDirectory";
import { DEFAULT_ROUTING_RULES } from "./routingRules";
import { sendAssignmentNotification } from "./email/emailService";
import { TicketingContext } from "./ticketingContextObject";

const STORAGE_KEY = "ticketing-store-v2";

function seedRoutingRules() {
  return DEFAULT_ROUTING_RULES.map((r, idx) => ({ id: `rule-${idx}`, ...r }));
}

function defaultStore() {
  return {
    tickets: [],
    nextSeq: 1001,
    teams: DEFAULT_TEAMS.map((t) => ({ ...t })),
    members: DEFAULT_MEMBERS.map((m) => ({ ...m })),
    routingRules: seedRoutingRules(),
    notifications: [],
  };
}

function loadStore() {
  if (typeof window === "undefined") return defaultStore();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultStore();
    const parsed = JSON.parse(raw);
    const fallback = defaultStore();
    return {
      tickets: Array.isArray(parsed.tickets) ? parsed.tickets : fallback.tickets,
      nextSeq: Number(parsed.nextSeq) || fallback.nextSeq,
      teams: Array.isArray(parsed.teams) && parsed.teams.length ? parsed.teams : fallback.teams,
      members: Array.isArray(parsed.members) ? parsed.members : fallback.members,
      routingRules: Array.isArray(parsed.routingRules) && parsed.routingRules.length ? parsed.routingRules : fallback.routingRules,
      notifications: Array.isArray(parsed.notifications) ? parsed.notifications : fallback.notifications,
    };
  } catch {
    return defaultStore();
  }
}

function withActivity(ticket, message) {
  return {
    ...ticket,
    activity: [...ticket.activity, { ts: new Date().toISOString(), message }],
  };
}

function slugify(name, existingKeys) {
  const base = String(name || "team").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "team";
  let key = base;
  let n = 2;
  while (existingKeys.includes(key)) {
    key = `${base}-${n}`;
    n += 1;
  }
  return key;
}

function makeMemberId(name, existingIds) {
  const base = String(name || "member").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "member";
  let id = base;
  let n = 2;
  while (existingIds.includes(id)) {
    id = `${base}-${n}`;
    n += 1;
  }
  return id;
}

/**
 * In-memory + localStorage store for tickets, teams, members, routing
 * rules, and simulated email notifications. Every mutating action here is
 * the seam a real backend integration would replace (e.g. `assignTicket`
 * becomes a POST to `/tickets/{id}/assign`, `simulateSend` becomes a real
 * SMTP/Graph/SendGrid call) without any UI component needing to change,
 * since components only ever reach this state through `useTicketing()`.
 */
export function TicketingProvider({ children }) {
  const [store, setStore] = useState(loadStore);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }, [store]);

  // ----------------------------
  // Ticket generation / dedup
  // ----------------------------
  const ensureTicketsForPayload = useCallback((rootCauses, sourceId) => {
    if (!Array.isArray(rootCauses) || !rootCauses.length || !sourceId) return;
    setStore((prev) => {
      const { tickets, nextSeq } = reconcileTicketsWithRootCauses(rootCauses, {
        sourceId,
        existingTickets: prev.tickets,
        routingRules: prev.routingRules,
        teams: prev.teams,
        nextSeq: prev.nextSeq,
      });
      if (tickets === prev.tickets) return prev;
      return { ...prev, tickets, nextSeq };
    });
  }, []);

  const loadDemoTickets = useCallback(() => {
    setStore((prev) => {
      const { tickets, nextSeq } = seedDemoTickets({
        existingTickets: prev.tickets,
        routingRules: prev.routingRules,
        teams: prev.teams,
        nextSeq: prev.nextSeq,
      });
      if (tickets === prev.tickets) return prev;
      return { ...prev, tickets, nextSeq };
    });
  }, []);

  const updateTicket = useCallback((id, updater) => {
    setStore((prev) => ({
      ...prev,
      tickets: prev.tickets.map((t) => (t.id === id ? updater(t) : t)),
    }));
  }, []);

  // ----------------------------
  // Assignment (+ simulated email)
  // ----------------------------
  const triggerAssignmentEmail = useCallback((ticket, member, teams) => {
    sendAssignmentNotification(ticket, member, teams).then((record) => {
      setStore((prev) => ({
        ...prev,
        notifications: [...prev.notifications, { ...record, ticketId: ticket.id }],
        tickets: prev.tickets.map((t) =>
          t.id === ticket.id
            ? withActivity(
                t,
                `Email sent to ${record.to.join(", ") || "assignee"}${record.cc.length ? ` (cc: ${record.cc.join(", ")})` : ""}.`
              )
            : t
        ),
      }));
    });
  }, []);

  const assignTicket = useCallback(
    (id, { teamKey, memberId }, note) => {
      const member = findMember(store.members, memberId);
      const team = findTeam(store.teams, teamKey);
      const existing = store.tickets.find((t) => t.id === id);
      if (!member || !existing) return;

      const nextStatus = existing.status === "Open" ? "Assigned" : existing.status;
      const message = `Assigned to ${member.name} (${team?.name || existing.team?.name || "Unknown Team"}).${note ? ` ${note}` : ""}`;
      const updated = withActivity(
        { ...existing, team: team || existing.team, assignee: { id: member.id, name: member.name }, status: nextStatus },
        message
      );

      setStore((prev) => ({ ...prev, tickets: prev.tickets.map((t) => (t.id === id ? updated : t)) }));
      triggerAssignmentEmail(updated, member, store.teams);
    },
    [store.members, store.teams, store.tickets, triggerAssignmentEmail]
  );

  const overrideAssignment = useCallback(
    (id, { teamKey, memberId }, recommendedName) => {
      assignTicket(id, { teamKey, memberId }, recommendedName ? `(Override of recommended assignee: ${recommendedName}.)` : "(Manual override.)");
    },
    [assignTicket]
  );

  const autoAssignTicket = useCallback(
    (id) => {
      const existing = store.tickets.find((t) => t.id === id);
      if (!existing) return;
      const recommendation = recommendAssignee(existing.rootCause, store.tickets, {
        teams: store.teams,
        members: store.members,
        routingRules: store.routingRules,
      });
      if (!recommendation) return;
      const { member, teamKey, reasons } = recommendation;
      const team = findTeam(store.teams, teamKey);
      const nextStatus = existing.status === "Open" ? "Assigned" : existing.status;
      const updated = withActivity(
        { ...existing, team: team || existing.team, assignee: { id: member.id, name: member.name }, status: nextStatus },
        `Auto-assigned to ${member.name} — ${reasons.join(", ")}.`
      );

      setStore((prev) => ({ ...prev, tickets: prev.tickets.map((t) => (t.id === id ? updated : t)) }));
      triggerAssignmentEmail(updated, member, store.teams);
    },
    [store.tickets, store.teams, store.members, store.routingRules, triggerAssignmentEmail]
  );

  const getRecommendation = useCallback(
    (rootCause) => recommendAssignee(rootCause, store.tickets, { teams: store.teams, members: store.members, routingRules: store.routingRules }),
    [store.tickets, store.teams, store.members, store.routingRules]
  );

  // ----------------------------
  // Lifecycle
  // ----------------------------
  const advanceStatus = useCallback(
    (id, targetStatus) => {
      updateTicket(id, (t) => withActivity({ ...t, status: targetStatus }, `Status changed to ${targetStatus}.`));
    },
    [updateTicket]
  );

  const startProgress = useCallback((id) => advanceStatus(id, "In Progress"), [advanceStatus]);
  const requestValidation = useCallback((id) => advanceStatus(id, "Pending Validation"), [advanceStatus]);
  const resolveTicket = useCallback((id) => advanceStatus(id, "Resolved"), [advanceStatus]);
  const closeTicket = useCallback((id) => advanceStatus(id, "Closed"), [advanceStatus]);

  const addNote = useCallback(
    (id, text) => {
      if (!text || !text.trim()) return;
      updateTicket(id, (t) => ({ ...t, notes: [...t.notes, { ts: new Date().toISOString(), text: text.trim() }] }));
    },
    [updateTicket]
  );

  // ----------------------------
  // Teams
  // ----------------------------
  const createTeam = useCallback((team) => {
    setStore((prev) => {
      const key = slugify(team.name, prev.teams.map((t) => t.key));
      return { ...prev, teams: [...prev.teams, { key, name: team.name, description: team.description || "", managerName: team.managerName || "", distributionEmail: team.distributionEmail || "" }] };
    });
  }, []);

  const updateTeam = useCallback((teamKey, updates) => {
    setStore((prev) => ({ ...prev, teams: prev.teams.map((t) => (t.key === teamKey ? { ...t, ...updates } : t)) }));
  }, []);

  const deleteTeam = useCallback(
    (teamKey) => {
      const hasMembers = store.members.some((m) => m.teamKey === teamKey);
      const hasRouting = store.routingRules.some((r) => r.teamKey === teamKey);
      if (hasMembers) return { success: false, reason: "This team still has members. Remove or reassign them first." };
      if (hasRouting) return { success: false, reason: "This team is still referenced by a routing rule. Update the routing rules first." };
      setStore((prev) => ({ ...prev, teams: prev.teams.filter((t) => t.key !== teamKey) }));
      return { success: true };
    },
    [store.members, store.routingRules]
  );

  // ----------------------------
  // Members
  // ----------------------------
  const addMember = useCallback((member) => {
    setStore((prev) => {
      const id = makeMemberId(member.name, prev.members.map((m) => m.id));
      return {
        ...prev,
        members: [
          ...prev.members,
          {
            id,
            name: member.name,
            email: member.email || "",
            role: member.role || "",
            teamKey: member.teamKey,
            skills: Array.isArray(member.skills) ? member.skills : [],
            specialty: member.skills?.[0] ? `${member.skills[0]} Specialist` : "Generalist",
            availability: member.availability || "Available",
          },
        ],
      };
    });
  }, []);

  const updateMember = useCallback((memberId, updates) => {
    setStore((prev) => ({ ...prev, members: prev.members.map((m) => (m.id === memberId ? { ...m, ...updates } : m)) }));
  }, []);

  const removeMember = useCallback((memberId) => {
    setStore((prev) => ({
      ...prev,
      members: prev.members.filter((m) => m.id !== memberId),
      tickets: prev.tickets.map((t) =>
        t.assignee?.id === memberId ? withActivity({ ...t, assignee: null }, "Unassigned — team member removed.") : t
      ),
    }));
  }, []);

  // ----------------------------
  // Routing rules
  // ----------------------------
  const addRoutingRule = useCallback((rule) => {
    setStore((prev) => ({
      ...prev,
      routingRules: [...prev.routingRules, { id: `rule-${Date.now()}`, rootCause: rule.rootCause, teamKey: rule.teamKey, requiredSkill: rule.requiredSkill || "" }],
    }));
  }, []);

  const updateRoutingRule = useCallback((ruleId, updates) => {
    setStore((prev) => ({ ...prev, routingRules: prev.routingRules.map((r) => (r.id === ruleId ? { ...r, ...updates } : r)) }));
  }, []);

  const removeRoutingRule = useCallback((ruleId) => {
    setStore((prev) => ({ ...prev, routingRules: prev.routingRules.filter((r) => r.id !== ruleId) }));
  }, []);

  const value = useMemo(
    () => ({
      tickets: store.tickets,
      teams: store.teams,
      members: store.members,
      routingRules: store.routingRules,
      notifications: store.notifications,
      ensureTicketsForPayload,
      loadDemoTickets,
      assignTicket,
      overrideAssignment,
      autoAssignTicket,
      getRecommendation,
      startProgress,
      requestValidation,
      resolveTicket,
      closeTicket,
      addNote,
      createTeam,
      updateTeam,
      deleteTeam,
      addMember,
      updateMember,
      removeMember,
      addRoutingRule,
      updateRoutingRule,
      removeRoutingRule,
    }),
    [
      store.tickets,
      store.teams,
      store.members,
      store.routingRules,
      store.notifications,
      ensureTicketsForPayload,
      loadDemoTickets,
      assignTicket,
      overrideAssignment,
      autoAssignTicket,
      getRecommendation,
      startProgress,
      requestValidation,
      resolveTicket,
      closeTicket,
      addNote,
      createTeam,
      updateTeam,
      deleteTeam,
      addMember,
      updateMember,
      removeMember,
      addRoutingRule,
      updateRoutingRule,
      removeRoutingRule,
    ]
  );

  return <TicketingContext.Provider value={value}>{children}</TicketingContext.Provider>;
}
