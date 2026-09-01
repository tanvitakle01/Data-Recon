import { useRef, useState } from "react";
import { Alert, Button, Input, Select, Textarea } from "@bristlecone/canopy";
import * as connectionsApi from "./connectionsApi";

const KIND_OPTIONS = [
  { value: "s4", label: "SAP S/4HANA" },
  { value: "ibp", label: "SAP IBP" },
];
const AUTH_TYPE_OPTIONS = [
  { value: "basic", label: "Basic (username/password)" },
  { value: "oauth2_client_credentials", label: "OAuth2 client credentials" },
  { value: "x509", label: "X.509 certificate" },
];
const ENVIRONMENT_OPTIONS = [
  { value: "dev", label: "Dev" },
  { value: "qa", label: "QA" },
  { value: "prod", label: "Prod" },
];

function secretPayloadFor(authType, secret) {
  if (authType === "basic") return { username: secret.username, password: secret.password };
  if (authType === "oauth2_client_credentials") {
    return { client_id: secret.clientId, client_secret: secret.clientSecret };
  }
  return {};
}

/**
 * Create/edit form. Secrets are write-only end to end: an edit never
 * receives the existing plaintext secret from the API (there's nothing to
 * prefill), so replacing credentials is always "type a new secret", never
 * "edit the old one" — `replacingSecret` gates whether the secret inputs
 * (and Test Connection) are even shown.
 */
function ConnectionForm({ existing, onSaved, onCancel }) {
  const isEdit = Boolean(existing);
  const [form, setForm] = useState({
    name: existing?.name ?? "",
    kind: existing?.kind ?? "s4",
    baseUrl: existing?.base_url ?? "",
    service: existing?.service ?? "",
    sapClient: existing?.sap_client ?? "",
    authType: existing?.auth_type ?? "basic",
    environment: existing?.environment ?? "dev",
    enabled: existing?.enabled ?? true,
  });
  const [secret, setSecret] = useState({ username: "", password: "", clientId: "", clientSecret: "" });
  const [replacingSecret, setReplacingSecret] = useState(!isEdit);
  // Unlike the secret above, the CA bundle isn't sensitive (it's a public
  // cert) so it round-trips from the API and prefills on edit.
  const [caBundlePem, setCaBundlePem] = useState(existing?.ca_bundle_pem ?? "");
  const [skipTlsVerify, setSkipTlsVerify] = useState(Boolean(existing?.skip_tls_verify));
  const [testResult, setTestResult] = useState(null);
  const [testToken, setTestToken] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const caFileInputRef = useRef(null);

  function updateForm(patch) {
    setForm((prev) => ({ ...prev, ...patch }));
    setTestToken(null);
    setTestResult(null);
  }

  function updateSecret(patch) {
    setSecret((prev) => ({ ...prev, ...patch }));
    setTestToken(null);
    setTestResult(null);
  }

  function updateTls(patch) {
    if ("caBundlePem" in patch) setCaBundlePem(patch.caBundlePem);
    if ("skipTlsVerify" in patch) setSkipTlsVerify(patch.skipTlsVerify);
    setTestToken(null);
    setTestResult(null);
  }

  function handleCaBundleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => updateTls({ caBundlePem: String(reader.result || "") });
    reader.readAsText(file);
  }

  function clearCaBundle() {
    updateTls({ caBundlePem: "" });
    if (caFileInputRef.current) caFileInputRef.current.value = "";
  }

  async function handleTest() {
    setTesting(true);
    setError("");
    try {
      const result = await connectionsApi.testConnection({
        kind: form.kind,
        base_url: form.baseUrl,
        service: form.service,
        sap_client: form.sapClient || null,
        auth_type: form.authType,
        ca_bundle_pem: caBundlePem || null,
        skip_tls_verify: skipTlsVerify,
        secret: secretPayloadFor(form.authType, secret),
      });
      setTestResult(result);
      setTestToken(result.success ? result.test_token : null);
    } catch {
      setTestResult({ success: false, message: "Could not run the test — please try again." });
      setTestToken(null);
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const payload = {
        name: form.name,
        base_url: form.baseUrl,
        service: form.service,
        sap_client: form.sapClient || null,
        auth_type: form.authType,
        environment: form.environment,
        enabled: form.enabled,
        ca_bundle_pem: caBundlePem || null,
        skip_tls_verify: skipTlsVerify,
      };
      if (!isEdit) payload.kind = form.kind;
      if (replacingSecret) {
        payload.secret = secretPayloadFor(form.authType, secret);
        payload.test_token = testToken;
      }

      if (isEdit) {
        await connectionsApi.updateConnection(existing.id, payload);
      } else {
        await connectionsApi.createConnection(payload);
      }
      onSaved();
    } catch (err) {
      setError(err.response?.data?.detail || "Could not save this connection.");
    } finally {
      setSaving(false);
    }
  }

  const canSave =
    form.name.trim() && form.baseUrl.trim() && form.service.trim() && (!replacingSecret || testToken);

  return (
    <div className="connection-form">
      {error && <Alert variant="error">{error}</Alert>}

      <Input label="Connection name" value={form.name} onChange={(e) => updateForm({ name: e.target.value })} required />

      <Select
        label="System type"
        options={KIND_OPTIONS}
        value={form.kind}
        onChange={(e) => updateForm({ kind: e.target.value })}
        disabled={isEdit}
      />

      <Select
        label="Environment"
        options={ENVIRONMENT_OPTIONS}
        value={form.environment}
        onChange={(e) => updateForm({ environment: e.target.value })}
      />

      <Input
        label="Base URL"
        value={form.baseUrl}
        onChange={(e) => updateForm({ baseUrl: e.target.value })}
        placeholder="https://host.example.com:port"
        required
      />
      <Input
        label="Service path"
        value={form.service}
        onChange={(e) => updateForm({ service: e.target.value })}
        placeholder="API_SALES_ORDER_SRV"
        required
      />
      <Input
        label="SAP client (optional)"
        value={form.sapClient}
        onChange={(e) => updateForm({ sapClient: e.target.value })}
      />

      <Select
        label="Auth type"
        options={AUTH_TYPE_OPTIONS}
        value={form.authType}
        onChange={(e) => updateForm({ authType: e.target.value })}
      />

      <div className="connection-form__secret">
        {!replacingSecret ? (
          <div className="connection-form__secret-masked">
            <span>•••••••• (saved)</span>
            <Button type="button" variant="outline" size="sm" onClick={() => setReplacingSecret(true)}>
              Replace credentials
            </Button>
          </div>
        ) : (
          <>
            {form.authType === "basic" && (
              <>
                <Input
                  label="Username"
                  value={secret.username}
                  onChange={(e) => updateSecret({ username: e.target.value })}
                  required
                />
                <Input
                  label="Password"
                  type="password"
                  value={secret.password}
                  onChange={(e) => updateSecret({ password: e.target.value })}
                  required
                />
              </>
            )}
            {form.authType === "oauth2_client_credentials" && (
              <>
                <Input
                  label="Client ID"
                  value={secret.clientId}
                  onChange={(e) => updateSecret({ clientId: e.target.value })}
                  required
                />
                <Input
                  label="Client secret"
                  type="password"
                  value={secret.clientSecret}
                  onChange={(e) => updateSecret({ clientSecret: e.target.value })}
                  required
                />
              </>
            )}
            {form.authType === "x509" && (
              <Alert variant="warning">X.509 authentication isn't supported by live testing yet.</Alert>
            )}
            {isEdit && (
              <Button type="button" variant="outline" size="sm" onClick={() => setReplacingSecret(false)}>
                Keep existing credentials instead
              </Button>
            )}
          </>
        )}
      </div>

      <div className="connection-form__tls">
        <p className="connection-form__tls-label">TLS verification</p>
        <p className="connection-form__tls-hint">
          Internal SAP hosts often use a corporate or self-signed CA that isn't in the default trust store. Upload
          it here rather than turning verification off.
        </p>
        <div className="connection-form__ca-row">
          <input
            ref={caFileInputRef}
            type="file"
            accept=".pem,.crt,.cer,.cert,application/x-pem-file,application/x-x509-ca-cert"
            onChange={handleCaBundleFile}
            className="connection-form__ca-file-input"
            id="ca-bundle-file"
          />
          <label htmlFor="ca-bundle-file" className="btn-secondary connection-form__ca-file-label">
            {caBundlePem ? "Replace CA bundle" : "Upload CA bundle (.pem/.crt)"}
          </label>
          {caBundlePem && (
            <Button type="button" variant="outline" size="sm" onClick={clearCaBundle}>
              Remove
            </Button>
          )}
        </div>
        {caBundlePem && (
          <Textarea
            label="CA bundle (PEM)"
            value={caBundlePem}
            onChange={(e) => updateTls({ caBundlePem: e.target.value })}
            rows={4}
            className="connection-form__ca-textarea"
          />
        )}

        <label className="connection-form__skip-verify">
          <input
            type="checkbox"
            checked={skipTlsVerify}
            onChange={(e) => updateTls({ skipTlsVerify: e.target.checked })}
          />
          Skip TLS verification (development only)
        </label>
        {skipTlsVerify && (
          <Alert variant="warning">
            Traffic to this host will not be authenticated — anything encrypted but unverified is vulnerable to
            interception. Do not use this for production connections.
          </Alert>
        )}
      </div>

      {testResult && <Alert variant={testResult.success ? "success" : "error"}>{testResult.message}</Alert>}

      <div className="connection-form__actions">
        <Button type="button" variant="outline" onClick={handleTest} loading={testing} disabled={!replacingSecret}>
          Test Connection
        </Button>
        <div className="connection-form__actions-right">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} loading={saving} disabled={!canSave}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

export default ConnectionForm;
