import axios from "axios";

// Backend origin. On Render the API is a separate web service, so its URL is
// only known at deploy time and is baked in at build time via
// VITE_API_BASE_URL. Empty string falls back to same-origin relative paths;
// the dev default points at the local uvicorn process.
// Exported because not every call goes through axios — the results download
// uses raw fetch() and must resolve against the same origin.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "http://localhost:8000" : "");

const baseURL = API_BASE_URL;

// No credentials: Stage-1 has no login and no session cookie, so there is
// nothing for the browser to attach.
const api = axios.create({ baseURL });

export default api;
