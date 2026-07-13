export function toneForStatus(status) {
  if (status === "Resolved" || status === "Closed") return "success";
  if (status === "In Progress" || status === "Pending Validation") return "info";
  if (status === "Assigned") return "warning";
  return "neutral"; // Open
}

export function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

export function formatTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function workloadTier(openCount) {
  if (openCount <= 1) return "Light";
  if (openCount <= 3) return "Moderate";
  return "Heavy";
}

export function formatRelativeShort(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
