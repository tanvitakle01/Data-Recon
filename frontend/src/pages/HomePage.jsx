import HomeContent from "../marketing/HomeContent";

/** Rendered inside AppLayout at "/home" — reuses the same Home design shown
 * on the public landing page ("/"), per product decision to have one Home
 * screen everywhere rather than a separate authenticated dashboard. */
function HomePage() {
  return <HomeContent authed />;
}

export default HomePage;
