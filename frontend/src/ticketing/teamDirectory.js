/**
 * Teams/members are now user-editable data owned by TicketingContext's
 * store, not a static config module. This file only holds the initial seed
 * (used the first time the store is created) and pure lookups that operate
 * on whatever teams/members array the caller currently has — so UI-created
 * teams/members work identically to the seeded ones everywhere they're read.
 */
export const DEFAULT_TEAMS = [
  {
    key: "masterData",
    name: "Master Data Team",
    description: "Handles product and location mapping issues.",
    managerName: "Sarah Johnson",
    distributionEmail: "masterdata@company.com",
  },
  {
    key: "sapIntegration",
    name: "SAP Integration Team",
    description: "Owns SAP/S4 integration and missing-record investigations.",
    managerName: "David Brown",
    distributionEmail: "sapintegration@company.com",
  },
  {
    key: "supplyPlanning",
    name: "Supply Planning Team",
    description: "Handles quantity variance and planning exception issues.",
    managerName: "Emma Davis",
    distributionEmail: "supplyplanning@company.com",
  },
];

export const DEFAULT_MEMBERS = [
  {
    id: "john-doe",
    name: "John Doe",
    email: "john@company.com",
    role: "Data Analyst",
    teamKey: "masterData",
    skills: ["Product Mapping"],
    specialty: "Product Mapping Specialist",
    availability: "Available",
  },
  {
    id: "priya-patel",
    name: "Priya Patel",
    email: "priya@company.com",
    role: "Data Analyst",
    teamKey: "masterData",
    skills: ["Location Mapping"],
    specialty: "Location Mapping Specialist",
    availability: "Available",
  },
  {
    id: "mike-smith",
    name: "Mike Smith",
    email: "mike@company.com",
    role: "Senior Data Analyst",
    teamKey: "masterData",
    skills: ["Product Mapping", "Location Mapping"],
    specialty: "Master Data Generalist",
    availability: "Busy",
  },
  {
    id: "sarah-johnson",
    name: "Sarah Johnson",
    email: "sarah.johnson@company.com",
    role: "Integration Lead",
    teamKey: "sapIntegration",
    skills: ["SAP Integration", "Missing Records"],
    specialty: "SAP Integration Specialist",
    availability: "Available",
  },
  {
    id: "david-brown",
    name: "David Brown",
    email: "david@company.com",
    role: "Integration Analyst",
    teamKey: "sapIntegration",
    skills: ["Missing Records"],
    specialty: "Missing Records Specialist",
    availability: "Out of Office",
  },
  {
    id: "alex-wilson",
    name: "Alex Wilson",
    email: "alex@company.com",
    role: "Planning Analyst",
    teamKey: "supplyPlanning",
    skills: ["Quantity Variance"],
    specialty: "Quantity Variance Specialist",
    availability: "Available",
  },
  {
    id: "emma-davis",
    name: "Emma Davis",
    email: "emma@company.com",
    role: "Senior Planning Analyst",
    teamKey: "supplyPlanning",
    skills: ["Planning Exceptions"],
    specialty: "Planning Exceptions Specialist",
    availability: "Available",
  },
];

export const AVAILABLE_SKILLS = [
  "Product Mapping",
  "Location Mapping",
  "SAP Integration",
  "Middleware",
  "Planning",
  "Data Quality",
  "Missing Records",
  "Quantity Variance",
  "Planning Exceptions",
];

export const AVAILABILITY_OPTIONS = ["Available", "Busy", "Out of Office"];

export function findTeam(teams, teamKey) {
  return (teams || []).find((t) => t.key === teamKey) || null;
}

export function findMember(members, memberId) {
  return (members || []).find((m) => m.id === memberId) || null;
}

export function membersForTeam(members, teamKey) {
  return (members || []).filter((m) => m.teamKey === teamKey);
}
