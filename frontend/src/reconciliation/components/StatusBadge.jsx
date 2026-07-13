// Tri-state status chip shared by the contract lifecycle and the
// transformation preview/approval lifecycle: pending (unknown yet), ok, fail.
function StatusBadge({ ok, label }) {
  if (ok === null || ok === undefined) {
    return <span className="contract-status contract-status--pending">• {label}</span>;
  }
  return ok ? (
    <span className="contract-status contract-status--ok">✓ {label}</span>
  ) : (
    <span className="contract-status contract-status--fail">✗ {label}</span>
  );
}

export default StatusBadge;
