// Light/dark theme preference. The palette itself lives in index.css: the
// prefers-color-scheme block themes the app from the OS setting, and a
// `data-theme` attribute on <html> overrides it in either direction.
//
// No stored value = follow the OS (and keep following it live, since the
// media query does that on its own). Once the user flips the header toggle,
// their pick is stored and written to `data-theme` on every load — the inline
// script in index.html applies it before first paint so there is no flash.

export const THEME_STORAGE_KEY = "dr-theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

export function readStoredTheme() {
  try {
    const v = window.localStorage.getItem(THEME_STORAGE_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export function storeTheme(theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Storage blocked (private mode, policy) — the choice still applies for
    // this page view, it just won't survive a reload.
  }
}

export function applyThemeAttribute(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export function systemTheme() {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

// Calls back with the new OS theme whenever the OS setting changes.
export function subscribeSystemTheme(callback) {
  const mql = window.matchMedia?.(DARK_QUERY);
  if (!mql) return () => {};
  const onChange = (e) => callback(e.matches ? "dark" : "light");
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}
