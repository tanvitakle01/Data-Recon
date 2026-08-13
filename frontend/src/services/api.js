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

