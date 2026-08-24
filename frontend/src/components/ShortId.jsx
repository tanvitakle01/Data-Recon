// Short-form display for a UUID-family identifier (run/batch/record/pair id
// — see backend/recon_engine/ids.py): shows the first 8 characters with the
// full value as a tooltip, and copies the FULL value to the clipboard on
// click — the pattern used anywhere a run/batch id appears in the UI or chat,
// so the id stays scannable inline without losing the full value a user
// might need to paste elsewhere (e.g. into an export or a support ticket).
import { useState } from "react";
import PropTypes from "prop-types";

function ShortId({ value, prefix = "" }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  const short = value.length > 8 ? value.slice(0, 8) : value;

  const copy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard API unavailable (permissions/insecure context) — the full
      // id is still reachable via the title tooltip, so this is a silent no-op.
    }
  };

  return (
    <button
      type="button"
      className="short-id mono"
      title={copied ? "Copied!" : value}
      onClick={copy}
    >
      {prefix}
      {short}
      {copied && <span className="short-id__copied">Copied</span>}
    </button>
  );
}

ShortId.propTypes = {
  value: PropTypes.string,
  prefix: PropTypes.string,
};

export default ShortId;
