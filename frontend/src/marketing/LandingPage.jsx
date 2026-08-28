import { useNavigate } from "react-router-dom";
import { BristleconeLogo } from "@bristlecone/canopy";
import canopyPkg from "@bristlecone/canopy/package.json";
import HomeContent from "./HomeContent";
import "./landingPage.css";

const NAV_LINKS = [
  { href: "#capabilities", label: "Platform" },
  { href: "#how", label: "How it works" },
  { href: "#demos", label: "Demos" },
  { href: "#support", label: "Support" },
];

/** Public, unauthenticated landing page at "/". Owns its own header/footer —
 * the authenticated "/home" destination reuses <HomeContent> without these,
 * since AppLayout already provides a header + sidebar there. */
function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="landing-page">
      <header className="landing-header">
        <BristleconeLogo size="sm" />
        <span className="landing-brand-divider" aria-hidden="true" />
        <span className="landing-brand-text">Data Reconciliation</span>
        <nav className="landing-nav" aria-label="Sections">
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="landing-nav-link">
              {link.label}
            </a>
          ))}
        </nav>
        <div className="landing-header-right">
          <span className="status-badge status-badge--extra">
            <span className="status-badge__dot" />
            S/4HANA connected
          </span>
          <button type="button" className="btn-primary" onClick={() => navigate("/login")}>
            Sign in
          </button>
        </div>
      </header>

      <HomeContent authed={false} />

      <footer className="landing-footer">
        <span className="landing-footer-text">Bristlecone · Data Reconciliation platform</span>
        <span className="landing-footer-version">Canopy {canopyPkg.version}</span>
      </footer>
    </div>
  );
}

export default LandingPage;
