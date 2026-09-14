import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Input, Alert } from "@bristlecone/canopy";
import { Check, Loader2, ShieldAlert, X } from "lucide-react";
import api, { setLlmSessionToken } from "../services/api";
import "./connections.css";

/** Connections — point the app's AI calls at your own billing plan.
 *
 * The override is session-scoped in the strictest sense: the key is held in
 * the backend's process memory, the handle to it is held in a JavaScript
 * variable (see services/api.js), and a page refresh loses both. Nothing here
 * is written to disk, a database, or a log line on either side.
 *
 * The key is only ever in this component's state between typing and saving —
 * once saved it is wiped from state and the server returns nothing but the
 * trailing four characters, so there is no path back to the full value.
 */
function ConnectionsPage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  // A pass is only valid for the exact values that were tested — editing
  // either field below invalidates it, so Save can never store credentials
  // that were not the ones proven to work.
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState(null);

  const refreshStatus = useCallback(async (signal) => {
    try {
      const res = await api.get("/api/connections/status", { signal });
      setStatus(res.data);
      setError(null);
    } catch (err) {
      if (err?.name === "CanceledError") return; // unmounted mid-flight
      setError("Could not reach the backend to read the current AI connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshStatus(controller.signal);
    return () => controller.abort();
  }, [refreshStatus]);

  const invalidateTest = () => setTestResult(null);

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    try {
      const res = await api.post("/api/connections/test", {
        api_key: apiKey,
        base_url: baseUrl.trim() || null,
      });
      setTestResult(res.data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setTestResult({
        ok: false,
        error: typeof detail === "string" ? detail : "The connection test could not be run.",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await api.post("/api/connections/override", {
        api_key: apiKey,
        base_url: baseUrl.trim() || null,
      });
      // Every subsequent request carries this token; the backend resolves it
      // to the stored key. The key itself leaves the browser here for good.
      setLlmSessionToken(res.data.session_token);
      setApiKey("");
      setTestResult(null);
      setStatus(res.data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not save the override.");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setClearing(true);
    setError(null);
    try {
      await api.delete("/api/connections/override");
    } catch {
      // Even if the call fails, dropping the token locally reverts this
      // browser to the default endpoint — the orphaned entry then ages out.
    } finally {
      setLlmSessionToken(null);
      setApiKey("");
      setBaseUrl("");
      setTestResult(null);
      setClearing(false);
      refreshStatus();
    }
  };

  const active = Boolean(status?.active);
  const defaults = status?.default ?? {};
  const busy = testing || saving || clearing;
  const canTest = apiKey.trim().length >= 8 && !busy;
  // Save is gated on a pass for the values currently in the fields. The
  // backend re-tests anyway and refuses to store a failing key, so this is the
  // visible half of a rule enforced in both places.
  const canSave = Boolean(testResult?.ok) && !busy;

  return (
    <div className="conn-page">
      <header className="conn-head">
        <h1 className="conn-h1">Connections</h1>
        <p className="conn-lede">
          Run this app&apos;s AI steps — mapping-sheet classification, header binding and value
          pairing — against your own billing plan instead of the built-in endpoint.
        </p>
      </header>

      {error && <Alert variant="error">{error}</Alert>}

      {/* ══ Card 1: what is in use right now ══ */}
      <section className="conn-card">
        <div className="conn-card__head">
          <h2 className="conn-card__title">Active AI endpoint</h2>
          <span className="conn-card__spacer" />
          {loading ? (
            <Badge variant="default">Checking…</Badge>
          ) : active ? (
            <Badge variant="success" dot>
              Your key
            </Badge>
          ) : (
            <Badge variant="default">App default</Badge>
          )}
        </div>
        <div className="conn-card__body">
          {/* The built-in connection is shown by MODEL ONLY — its endpoint,
              auth and credentials are deliberately not surfaced here, and the
              header badge already says which of the two is in use. An override
              adds rows for what the user themselves supplied. */}
          <dl className="conn-dl">
            <dt>Model</dt>
            <dd className="mono">{defaults.model || "Not configured"}</dd>

            {active && (
              <>
                <dt>Key</dt>
                <dd className="mono">{status.masked_key}</dd>

                <dt>Endpoint</dt>
                <dd className="mono">
                  {status.base_url || (
                    <span className="conn-muted">
                      The app&apos;s built-in endpoint — no base URL entered.
                    </span>
                  )}
                </dd>
              </>
            )}
          </dl>

          {active && (
            <div className="conn-actions">
              <Button variant="outline" size="sm" onClick={handleClear} disabled={busy}>
                {clearing ? (
                  <Loader2 size={12} className="animate-spin" aria-hidden />
                ) : (
                  <X size={12} aria-hidden />
                )}
                Clear override
              </Button>
              <span className="conn-muted">Reverts every AI call to the app&apos;s endpoint.</span>
            </div>
          )}
        </div>
      </section>

      {/* ══ Card 2: enter an override ══ */}
      <section className="conn-card">
        <div className="conn-card__head">
          <h2 className="conn-card__title">
            {active ? "Replace your key" : "Use your own API key"}
          </h2>
        </div>
        <div className="conn-card__body conn-card__body--stack">
          <div className="conn-field">
            <Input
              id="conn-api-key"
              label="API key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={active ? `Currently ${status.masked_key}` : "Paste your key"}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                invalidateTest();
              }}
              hint="Sent to the backend once, held in memory, and never returned in full."
            />
          </div>

          <div className="conn-field">
            <Input
              id="conn-base-url"
              label="Base URL (optional)"
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="https://…"
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
                invalidateTest();
              }}
              hint="Leave blank to use the app's built-in endpoint with your key."
            />
          </div>

          <div className="conn-actions">
            <Button variant="outline" size="sm" onClick={handleTest} disabled={!canTest}>
              {testing ? (
                <>
                  <Loader2 size={12} className="animate-spin" aria-hidden /> Testing…
                </>
              ) : (
                "Test connection"
              )}
            </Button>
            <Button variant="primary" size="sm" onClick={handleSave} disabled={!canSave}>
              {saving ? (
                <>
                  <Loader2 size={12} className="animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                "Save"
              )}
            </Button>
            {!testResult && !busy && (
              <span className="conn-muted">Test the key before it can be saved.</span>
            )}
          </div>

          {testResult?.ok && (
            <p className="conn-result is-pass">
              <Check size={14} aria-hidden /> Connection succeeded
              {baseUrl.trim() ? ` against ${baseUrl.trim()}` : ""}. Save to use this key for the
              session.
            </p>
          )}
          {testResult && !testResult.ok && (
            <p className="conn-result is-fail">
              <ShieldAlert size={14} aria-hidden />
              <span>
                Connection failed — nothing was saved.
                <span className="conn-result__detail">{testResult.error}</span>
              </span>
            </p>
          )}
        </div>
      </section>

      <p className="conn-note">
        Stored for this session only — cleared on refresh, never written to disk.
      </p>
    </div>
  );
}

export default ConnectionsPage;
