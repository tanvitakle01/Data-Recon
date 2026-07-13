import { FiClock } from "react-icons/fi";

/**
 * Shared premium empty-state for not-yet-built pages. Three pages previously
 * duplicated the same plain gray "Coming soon" box; this gives them one
 * consistent, intentional-looking treatment without fabricating features
 * that don't exist yet.
 */
export default function ComingSoon({ note }) {
  return (
    <div className="surface-elevated accent-bar accent-bar-lav" style={{ marginTop: 18, padding: 28, textAlign: "center" }}>
      <div
        style={{
          margin: "0 auto 14px",
          height: 48,
          width: 48,
          borderRadius: 16,
          background: "rgba(99,102,241,0.12)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <FiClock size={22} color="#4f46e5" />
      </div>
      <div style={{ fontWeight: 850, fontSize: 15, color: "#0f172a" }}>Coming soon</div>
      <div style={{ color: "#64748b", fontWeight: 600, marginTop: 6, maxWidth: 440, marginLeft: "auto", marginRight: "auto" }}>
        {note}
      </div>
    </div>
  );
}
