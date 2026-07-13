// Explicit connection stage shared by the SAP S/4HANA and SAP IBP dataset
// workspaces. Before this existed, both workspaces fired their metadata
// requests on mount, so a user who merely *selected* a SAP connector saw
// "Entities: 0 / Network Error" before ever asking to connect. These pieces
// gate the workspace behind a deliberate "Connect & Load Metadata" action and
// give connecting/error/connected states their own dedicated surfaces.
//
// Presentational only — the parent workspace owns the connection state machine
// and passes the handlers/counters in.

// Idle: the user picked a SAP connector but hasn't loaded metadata yet.
export function SapConnectPrompt({ serviceName, description, onConnect }) {
  return (
    <div className="ibpw-root">
      <div className="sapc-gate">
        <span className="sapc-gate__icon" aria-hidden="true">
          🔌
        </span>
        <h3 className="sapc-gate__title">{serviceName}</h3>
        <p className="sapc-gate__desc">{description}</p>
        <button type="button" className="sapc-btn" onClick={onConnect}>
          Connect &amp; Load Metadata
        </button>
      </div>
    </div>
  );
}

// Connecting: metadata request in flight. Skeleton loaders rather than an
// empty explorer, per the UX requirement.
export function SapConnecting({ serviceName }) {
  return (
    <div className="ibpw-root">
      <div className="sapc-gate sapc-gate--busy">
        <span className="sapc-btn__spin sapc-gate__spin" aria-hidden="true" />
        <h3 className="sapc-gate__title">Connecting to {serviceName}…</h3>
        <p className="sapc-gate__desc">Loading metadata…</p>
        <div className="sapc-skel">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="ibpw-skel sapc-skel__row" />
          ))}
        </div>
      </div>
    </div>
  );
}

// Error: metadata never loaded. Explains likely causes and offers a retry —
// never the bare "Entities: 0" explorer.
export function SapConnectError({ serviceName, error, onRetry }) {
  return (
    <div className="ibpw-root">
      <div className="sapc-error">
        <span className="sapc-error__icon" aria-hidden="true">
          ⚠
        </span>
        <h3 className="sapc-error__title">Unable to connect to {serviceName}</h3>
        <p className="sapc-error__label">Possible causes:</p>
        <ul className="sapc-error__causes">
          <li>Backend API unavailable</li>
          <li>SAP credentials invalid</li>
          <li>VPN/network issue</li>
          <li>SAP endpoint unreachable</li>
        </ul>
        {error && <p className="sapc-error__detail">{String(error)}</p>}
        <button type="button" className="sapc-btn sapc-btn--retry" onClick={onRetry}>
          Retry Connection
        </button>
      </div>
    </div>
  );
}

// Connected: success banner + top action bar rendered above the workspace.
// `showImport` defaults to true for backward compatibility; Card 3 of the
// progressive-disclosure workspace layout passes `showImport={false}` since
// the Dataset Summary panel already carries the one Import action for that
// screen and duplicating it here would be visual clutter.
export function SapConnectedBar({
  entitiesCount,
  propertiesCount,
  onRefresh,
  onReconnect,
  onImport,
  refreshing = false,
  importing = false,
  importDisabled = false,
  showImport = true,
}) {
  return (
    <div className="sapc-bar">
      <div className="sapc-bar__status">
        <span className="sapc-bar__badge">✓ Connected</span>
        <div className="sapc-bar__stats">
          <span className="sapc-bar__stat">
            <strong>{entitiesCount}</strong> Entities Discovered
          </span>
          {propertiesCount != null && (
            <span className="sapc-bar__stat">
              <strong>{propertiesCount}</strong> Properties Available
            </span>
          )}
        </div>
      </div>
      <div className="sapc-bar__actions">
        <button
          type="button"
          className="sapc-actionbtn"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing && <span className="ibpw-btn__spin sapc-actionbtn__spin" />}
          Refresh Metadata
        </button>
        <button type="button" className="sapc-actionbtn" onClick={onReconnect}>
          Reconnect
        </button>
        {showImport && (
          <button
            type="button"
            className="sapc-actionbtn sapc-actionbtn--primary"
            onClick={onImport}
            disabled={importDisabled || importing}
          >
            {importing && <span className="ibpw-btn__spin sapc-actionbtn__spin" />}
            Import Dataset
          </button>
        )}
      </div>
    </div>
  );
}

// Connected, not yet building (Card 2 of the progressive-disclosure layout):
// shows the same "connected" status as SapConnectedBar but withholds the
// entity browser/import action until the user deliberately continues — the
// UX requirement that no entity data appears on the initial connection card.
export function SapConnectedSummary({
  serviceName,
  entitiesCount,
  onRefresh,
  onReconnect,
  onContinue,
  refreshing = false,
}) {
  return (
    <div className="ibpw-root">
      <div className="sapc-gate sapc-gate--connected">
        <span className="sapc-gate__icon" aria-hidden="true">
          ✓
        </span>
        <h3 className="sapc-gate__title">Connected to {serviceName}</h3>
        <p className="sapc-gate__desc">
          <strong>{entitiesCount}</strong> {entitiesCount === 1 ? "entity" : "entities"} discovered.
        </p>
        <div className="sapc-gate__actions">
          <button
            type="button"
            className="sapc-actionbtn"
            onClick={onRefresh}
            disabled={refreshing}
          >
            {refreshing && <span className="ibpw-btn__spin sapc-actionbtn__spin" />}
            Refresh Metadata
          </button>
          <button type="button" className="sapc-actionbtn" onClick={onReconnect}>
            Reconnect
          </button>
          <button type="button" className="sapc-btn" onClick={onContinue}>
            Continue to Build Dataset
          </button>
        </div>
      </div>
    </div>
  );
}
