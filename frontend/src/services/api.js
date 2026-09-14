import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000",
  // The session lives in an httpOnly cookie, not a header we set — without
  // this, the browser never sends it and every request looks unauthenticated.
  withCredentials: true,
});

// Set by AuthProvider on mount. A 401 anywhere (session expired, revoked, or
// simply never authenticated) drops the app back to "anonymous" without a
// full page reload — this module has no React context of its own, so the
// callback is the seam.
let onUnauthorized = null;

export function registerUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

// ── LLM endpoint override session token ─────────────────────────────────────
// Deliberately a module-scope variable and NOT localStorage/sessionStorage/a
// cookie: a page refresh re-evaluates this module, the token is gone, and the
// backend reverts to the app's default endpoint. That is the whole "cleared on
// refresh, never written to disk" guarantee the Connections page states — it
// is enforced here, by where this value lives.
//
// The token is an opaque handle. The API key itself never comes back from the
// server after being saved, so it is never held in browser memory either.
let llmSessionToken = null;

export function setLlmSessionToken(token) {
  llmSessionToken = token || null;
}

export function getLlmSessionToken() {
  return llmSessionToken;
}

// Attached to EVERY request, not just LLM ones: any route may reach an LLM
// call site, and the backend resolves the override once in middleware.
api.interceptors.request.use((config) => {
  if (llmSessionToken) {
    config.headers["X-Recon-Session"] = llmSessionToken;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    return Promise.reject(error);
  }
);

export default api;

