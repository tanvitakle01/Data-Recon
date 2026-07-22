import { Badge } from "@bristlecone/canopy";

// Tri-state status chip shared by the contract lifecycle and the
// transformation preview/approval lifecycle: pending (unknown yet), ok, fail.
// Renders as a Canopy Badge — default (gray) while unknown, success once ok,
// error on failure; the ✓/✗/• glyph is kept so state reads without relying on
// color alone.
function StatusBadge({ ok, label }) {
  if (ok === null || ok === undefined) {
    return <Badge variant="default">• {label}</Badge>;
  }
  return ok ? (
    <Badge variant="success">✓ {label}</Badge>
  ) : (
    <Badge variant="error">✗ {label}</Badge>
  );
}

export default StatusBadge;
