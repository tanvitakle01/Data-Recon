import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import {
  SapConnectPrompt,
  SapConnecting,
  SapConnectError,
  SapConnectedBar,
  SapConnectedSummary,
} from "./SapConnectionGate";
import { exportDatasetToCsv } from "../../utils/csvExport";
import {
  IBP_TRANSFORMATION_DISCOVERY_FIELDS,
  recommendedFieldsFor,
} from "../lib/transformationDiscoveryFields";
import "./ibpWorkspace.css";

// SAP IBP dataset workspace — a three-pane data-exploration surface used in
// the wizard's Step 3 (Target) when the IBP connector is selected.
//
// Left   : Entity Explorer   — search + recently used + entity list.
// Center : Column Explorer    (top) and Live Preview grid (bottom).
// Right  : Dataset Summary    — stats, import readiness, and the import action.
//
// It drives the existing metadata-driven endpoints
// (`/api/connectors/ibp/...`) unchanged and, once the user imports, hands the
// dataset back through `onLoaded({ columns, preview, rows, rowCount })` — the
// same contract the wizard's SapFetchPanel uses — so downstream steps treat it
// like any other dataset. No backend or data-flow behaviour is changed here.

const PREVIEW_DEBOUNCE_MS = 400;
const DEFAULT_COL_WIDTH = 150;

function looksNumeric(v) {
  if (v === null || v === undefined || v === "") return false;
  if (typeof v === "number") return true;
  const s = String(v).trim();
  return s !== "" && !Number.isNaN(Number(s));
}

function IbpDatasetWorkspace({ onLoaded, dataset, onStageChange }) {
  // ---- connection stage ----
  // Metadata is no longer fetched on mount; the user must explicitly connect.
  // "idle" → connect prompt, "connecting" → skeletons, "error" → retry card,
  // "connected" → the workspace. A pre-existing dataset (navigating back into
  // the step) auto-reconnects so the explorer is usable again.
  // Returning users (a dataset is already in wizard state) start in the
  // connecting state so they see skeletons, not a flash of the connect prompt,
  // before the auto-reconnect effect reloads metadata.
  const [connState, setConnState] = useState(dataset ? "connecting" : "idle");
  const [connError, setConnError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // ---- card stage (progressive disclosure within the workspace) ----
  // "connect" → connected-summary only (Card 2), "build" → the full
  // entity/column workspace (Card 3), "preview" → imported dataset preview
  // only (Card 4). Initialized from `dataset` (not an effect) so a returning
  // user with an already-imported dataset lands straight on the preview card
  // with no flash of the earlier cards.
  const [stage, setStage] = useState(dataset ? "preview" : "connect");
  useEffect(() => {
    onStageChange?.(stage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  // ---- entities ----
  const [entities, setEntities] = useState([]);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [selectedEntity, setSelectedEntity] = useState("");
  const [recent, setRecent] = useState([]);

  // ---- properties ----
  const [properties, setProperties] = useState([]); // [{name,type,role,label,selectable}]
  const [selected, setSelected] = useState([]);
  const [propFilter, setPropFilter] = useState("");
  const [entityLoading, setEntityLoading] = useState(false);
  // Fields auto-checked by a Transformation Discovery rule (e.g. selecting
  // PRDID also checks PRODDESC, PRODTYPE, ...) — tracked separately so the
  // "Recommended" badge only marks the supporting fields, not the trigger
  // field itself, and clears once a field is deselected.
  const [autoSelected, setAutoSelected] = useState(new Set());

  // ---- preview ----
  const [previewRows, setPreviewRows] = useState([]);
  const [previewCols, setPreviewCols] = useState([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [sort, setSort] = useState({ col: null, dir: "asc" });
  const [colWidths, setColWidths] = useState({});

  // ---- import ----
  const [fetching, setFetching] = useState(false);
  const [imported, setImported] = useState(Boolean(dataset));
  const [importedCount, setImportedCount] = useState(dataset?.rowCount ?? null);
  const [error, setError] = useState(null);

  // Snapshot of the actual imported dataset (not the live-preview request),
  // used to render the post-import "Imported Dataset Preview". Seeded from the
  // wizard's stored dataset so it survives navigating back into the step.
  const [importedPreview, setImportedPreview] = useState(
    dataset
      ? {
          entity: null,
          columns: dataset.columns ?? [],
          rows: (dataset.preview ?? []).slice(0, 10),
          rowCount: dataset.rowCount ?? 0,
        }
      : null
  );

  // ---- export (full dataset, exactly as received — not the 10-row preview) ----
  const [importedRows, setImportedRows] = useState(dataset?.rows ?? null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  // ---- Connect & load metadata (Step 1: discover entities) ----
  // Triggered explicitly by the connect prompt / Refresh Metadata, not on
  // mount. `refresh` keeps the workspace visible (entity-list skeleton only)
  // instead of dropping back to the full-screen connecting state.
  const connect = useCallback(async ({ refresh = false } = {}) => {
    if (refresh) setRefreshing(true);
    else setConnState("connecting");
    setEntitiesLoading(true);
    setConnError(null);
    try {
      const res = await api.get("/api/connectors/ibp/entities");
      const payload = res.data ?? {};
      if (!payload.success) {
        setConnError(payload.error || "Failed to load IBP entities");
        setConnState("error");
        return;
      }
      setEntities(payload.entities ?? []);
      setConnState("connected");
    } catch (err) {
      setConnError(err?.message || String(err));
      setConnState("error");
    } finally {
      setEntitiesLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Reconnect: discard the loaded metadata/selection and return to the
  // connect prompt for a clean start.
  const reconnect = useCallback(() => {
    setEntities([]);
    setSelectedEntity("");
    setProperties([]);
    setSelected([]);
    setEntityFilter("");
    setPropFilter("");
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setError(null);
    setConnError(null);
    setConnState("idle");
    setStage("connect");
  }, []);

  // A dataset already in wizard state means the user connected before and is
  // navigating back — transparently reconnect so the explorer isn't empty.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    // Run-once fetch-on-mount for the returning-user case; connect() sets the
    // connecting state before awaiting the metadata request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (dataset) connect();
  }, [dataset, connect]);

  const filteredEntities = useMemo(() => {
    const q = entityFilter.trim().toLowerCase();
    if (!q) return entities;
    return entities.filter(
      (e) =>
        e.name.toLowerCase().includes(q) ||
        (e.entity_type || "").toLowerCase().includes(q)
    );
  }, [entities, entityFilter]);

  const selectableProps = useMemo(
    () => properties.filter((p) => p.selectable),
    [properties]
  );

  // ---- Step 2: pick entity → load properties + default selection ----
  const chooseEntity = useCallback(async (entityName) => {
    setSelectedEntity(entityName);
    setProperties([]);
    setSelected([]);
    setAutoSelected(new Set());
    setPropFilter("");
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setSort({ col: null, dir: "asc" });
    setColWidths({});
    setImported(false);
    setError(null);

    if (!entityName) return;

    setRecent((prev) => [entityName, ...prev.filter((n) => n !== entityName)].slice(0, 5));
    setEntityLoading(true);
    try {
      const res = await api.get(
        `/api/connectors/ibp/entities/${encodeURIComponent(entityName)}/properties`
      );
      const payload = res.data ?? {};
      if (!payload.success) {
        setError(payload.error || "Failed to load properties");
        return;
      }
      const props = payload.properties ?? [];
      setProperties(props);
      const selectable = new Set(props.filter((p) => p.selectable).map((p) => p.name));
      setSelected((payload.default_properties ?? []).filter((n) => selectable.has(n)));
    } catch (err) {
      setError(`Failed to load entity metadata: ${err?.message || err}`);
    } finally {
      setEntityLoading(false);
    }
  }, []);

  // ---- Step 3: column selection ----
  const filteredProps = useMemo(() => {
    const q = propFilter.trim().toLowerCase();
    if (!q) return selectableProps;
    return selectableProps.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.label || "").toLowerCase().includes(q)
    );
  }, [selectableProps, propFilter]);

  // Any change to the selection invalidates a prior import, so the readiness
  // and summary reflect that the wizard's stored dataset is now stale.
  //
  // Checking a Transformation Discovery trigger field (e.g. PRDID, LOCID)
  // also checks its supporting attributes, filtered to whatever actually
  // exists on this entity — missing ones are skipped silently. The user can
  // still deselect any of them individually afterward.
  const toggleProp = (name) => {
    setImported(false);
    setSelected((prev) => {
      if (prev.includes(name)) {
        setAutoSelected((autoPrev) => {
          if (!autoPrev.has(name)) return autoPrev;
          const next = new Set(autoPrev);
          next.delete(name);
          return next;
        });
        return prev.filter((n) => n !== name);
      }

      const availableNames = selectableProps.map((p) => p.name);
      const recommended = recommendedFieldsFor(
        IBP_TRANSFORMATION_DISCOVERY_FIELDS,
        name,
        availableNames
      );
      if (recommended.length === 0) return [...prev, name];

      const newlyAdded = recommended.filter((f) => f !== name && !prev.includes(f));
      if (newlyAdded.length > 0) {
        setAutoSelected((autoPrev) => new Set([...autoPrev, ...newlyAdded]));
      }
      return Array.from(new Set([...prev, ...recommended]));
    });
  };
  const selectAll = () => {
    setImported(false);
    setSelected(selectableProps.map((p) => p.name));
    setAutoSelected(new Set());
  };
  const deselectAll = () => {
    setImported(false);
    setSelected([]);
    setAutoSelected(new Set());
  };

  const orderedSelected = useMemo(
    () => selectableProps.map((p) => p.name).filter((n) => selected.includes(n)),
    [selectableProps, selected]
  );

  // ---- Live preview: debounced re-fetch whenever selection changes ----
  const previewKey = useMemo(
    () => `${selectedEntity}::${orderedSelected.join(",")}`,
    [selectedEntity, orderedSelected]
  );
  const previewTimer = useRef(null);

  useEffect(() => {
    // Only fetch while Card 3 (Build Dataset) is actually visible — no point
    // refreshing a live preview the user can't see.
    if (!selectedEntity || orderedSelected.length === 0 || stage !== "build") {
      return undefined;
    }
    let cancelled = false;
    clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(async () => {
      setPreviewLoading(true);
      setPreviewError(null);
      try {
        const res = await api.post("/api/connectors/ibp/preview", {
          entity: selectedEntity,
          properties: orderedSelected,
        });
        const payload = res.data ?? {};
        if (cancelled) return;
        if (!payload.success) {
          setPreviewError(payload.error || "Preview failed");
          setPreviewRows([]);
          setPreviewCols([]);
          return;
        }
        setPreviewRows(payload.rows ?? []);
        setPreviewCols(payload.columns ?? orderedSelected);
      } catch (err) {
        if (!cancelled) setPreviewError(`Preview failed: ${err?.message || err}`);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(previewTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey, stage]);

  // ---- Grid: sort + resizable columns ----
  const sortedRows = useMemo(() => {
    if (!sort.col) return previewRows;
    const dir = sort.dir === "asc" ? 1 : -1;
    const numeric = previewRows.every((r) => looksNumeric(r[sort.col]));
    return [...previewRows].sort((a, b) => {
      const av = a[sort.col];
      const bv = b[sort.col];
      if (numeric) return (Number(av) - Number(bv)) * dir;
      return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
    });
  }, [previewRows, sort]);

  const toggleSort = (col) =>
    setSort((prev) =>
      prev.col === col
        ? { col, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { col, dir: "asc" }
    );

  const resizeRef = useRef(null);
  const startResize = (e, col) => {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startW = colWidths[col] ?? DEFAULT_COL_WIDTH;
    resizeRef.current = { col, startX, startW };

    const onMove = (ev) => {
      const r = resizeRef.current;
      if (!r) return;
      const next = Math.max(70, r.startW + (ev.clientX - r.startX));
      setColWidths((prev) => ({ ...prev, [r.col]: next }));
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // ---- Step 4: import full dataset ----
  const importDataset = async () => {
    if (!selectedEntity || orderedSelected.length === 0) return;
    setFetching(true);
    setError(null);
    try {
      const res = await api.post("/api/connectors/ibp/fetch", {
        entity: selectedEntity,
        properties: orderedSelected,
      });
      const payload = res.data ?? {};
      if (!payload.success) {
        setError(payload.error || "Failed to fetch dataset");
        return;
      }
      const rows = payload.rows ?? [];
      const columns = payload.columns ?? orderedSelected;
      setImported(true);
      setImportedCount(rows.length);
      // Post-import preview built from the actual fetched dataset.
      setImportedPreview({
        entity: selectedEntity,
        columns,
        rows: rows.slice(0, 10),
        rowCount: rows.length,
      });
      setImportedRows(rows);
      setStage("preview");
      // Fields auto-checked by a Transformation Discovery rule (MDT/recommended
      // fields) — carried along so downstream mapping generation can exclude
      // them while they remain selectable here for tracking/validation.
      onLoaded?.({
        columns,
        preview: rows.slice(0, 10),
        rows,
        rowCount: rows.length,
        mdtFields: Array.from(autoSelected),
      });
    } catch (err) {
      setError(`Failed to fetch dataset: ${err?.message || err}`);
    } finally {
      setFetching(false);
    }
  };

  // ---- download imported dataset as CSV (client-side, no re-fetch) ----
  const downloadDataset = async () => {
    if (!importedPreview || !importedRows?.length) return;
    setDownloadError(null);
    setDownloading(true);
    try {
      await exportDatasetToCsv({
        sourceSystem: "IBP",
        datasetName: importedPreview.entity || selectedEntity,
        columns: importedPreview.columns,
        rows: importedRows,
      });
    } catch (err) {
      setDownloadError(`Failed to export dataset: ${err?.message || err}`);
    } finally {
      setDownloading(false);
    }
  };

  const readiness = imported
    ? { cls: "done", icon: "✓", text: `Dataset imported · ${importedCount ?? 0} rows` }
    : orderedSelected.length > 0 && !previewError
      ? { cls: "ready", icon: "◆", text: "Ready to import" }
      : { cls: "wait", icon: "○", text: "Select columns to import" };

  const previewStatus = previewLoading
    ? { cls: "amber", text: "Loading…" }
    : previewError
      ? { cls: "red", text: "Preview error" }
      : previewRows.length > 0
        ? { cls: "accent", text: `Live · ${previewRows.length} rows` }
        : null;

  // ---- Connection gate: don't render the explorer until metadata loads ----
  if (connState === "idle") {
    return (
      <SapConnectPrompt
        serviceName="SAP IBP"
        description="Connect to your SAP IBP service to discover planning entities and available attributes/key figures."
        onConnect={() => connect()}
      />
    );
  }
  if (connState === "connecting") {
    return <SapConnecting serviceName="SAP IBP" />;
  }
  if (connState === "error") {
    return (
      <SapConnectError
        serviceName="SAP IBP"
        error={connError}
        onRetry={() => connect()}
      />
    );
  }

  // ---- Card 2: connected, not yet building — no entity browser yet ----
  if (stage === "connect") {
    return (
      <SapConnectedSummary
        serviceName="SAP IBP"
        entitiesCount={entities.length}
        onRefresh={() => connect({ refresh: true })}
        onReconnect={reconnect}
        onContinue={() => setStage("build")}
        refreshing={refreshing}
      />
    );
  }

  // ---- Card 4: imported dataset preview only — the sole screen that shows
  // actual data rows. "Back"/"Re-import" both return to Card 3 without
  // clearing any entity/column selections (the workspace never unmounts).
  if (stage === "preview") {
    return (
      <div className="ibpw-root">
        {imported && importedPreview && importedPreview.rows.length > 0 && (
          <section className="ibpw-panel ibpw-imported">
            <header className="ibpw-panel__head">
              <h4 className="ibpw-panel__title">Imported Dataset Preview</h4>
              <span className="ibpw-spacer" />
              {importedPreview.entity && (
                <span className="ibpw-badge ibpw-badge--count">{importedPreview.entity}</span>
              )}
              <span className="ibpw-badge ibpw-badge--accent">
                {importedPreview.rowCount.toLocaleString()} rows
              </span>
              <span className="ibpw-badge ibpw-badge--count">
                {importedPreview.columns.length} cols
              </span>
              <button
                type="button"
                className="ibpw-btn ibpw-btn--ghost ibpw-btn--header"
                onClick={downloadDataset}
                disabled={downloading || fetching || !importedRows?.length}
              >
                {downloading && <span className="ibpw-btn__spin" />}
                {downloading ? "Preparing…" : "Download Data"}
              </button>
            </header>
            {downloadError && <p className="ibpw-summary__error">⚠️ {downloadError}</p>}

            <div className="ibpw-grid-wrap">
              <table className="ibpw-grid">
                <colgroup>
                  {importedPreview.columns.map((c) => (
                    <col key={c} style={{ width: DEFAULT_COL_WIDTH }} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    {importedPreview.columns.map((c) => (
                      <th key={c} style={{ position: "sticky" }}>
                        <div className="ibpw-grid__th-inner">
                          <span className="ibpw-grid__th-label" title={c}>
                            {c}
                          </span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {importedPreview.rows.map((row, idx) => (
                    <tr key={idx}>
                      {importedPreview.columns.map((c) => (
                        <td
                          key={c}
                          className={looksNumeric(row[c]) ? "ibpw-grid__num" : ""}
                          title={row[c] != null ? String(row[c]) : ""}
                        >
                          {row[c] != null ? String(row[c]) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="ibpw-imported__caption">
              Showing {importedPreview.rows.length} of{" "}
              {importedPreview.rowCount.toLocaleString()} rows
            </p>
          </section>
        )}

        <div className="ibpw-card-actions">
          <button type="button" className="ibpw-btn ibpw-btn--ghost" onClick={() => setStage("build")}>
            Back
          </button>
          <button
            type="button"
            className="ibpw-btn"
            onClick={importDataset}
            disabled={fetching || orderedSelected.length === 0}
          >
            {fetching && <span className="ibpw-btn__spin" />}
            {fetching ? "Importing…" : "Re-import Dataset"}
          </button>
        </div>
        {error && <p className="ibpw-summary__error">⚠️ {String(error)}</p>}
      </div>
    );
  }

  // ---- Card 3: Build Dataset — entity/column workspace ----
  return (
    <div className="ibpw-root">
    <SapConnectedBar
      entitiesCount={entities.length}
      propertiesCount={selectedEntity ? selectableProps.length : null}
      onRefresh={() => connect({ refresh: true })}
      onReconnect={reconnect}
      refreshing={refreshing}
      showImport={false}
    />
    <div className="ibpw">
      {/* ---------------- LEFT: Entity Explorer ---------------- */}
      <div className="ibpw__col ibpw__col--left">
        <section className="ibpw-panel">
          <header className="ibpw-panel__head">
            <h4 className="ibpw-panel__title">Entities</h4>
            <span className="ibpw-spacer" />
            {!entitiesLoading && (
              <span className="ibpw-badge ibpw-badge--count">{entities.length}</span>
            )}
          </header>

          <div className="ibpw-panel__body" style={{ paddingBottom: 6 }}>
            <div className="ibpw-search">
              <span className="ibpw-search__icon">⌕</span>
              <input
                className="ibpw-input"
                type="text"
                placeholder="Search entities…"
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
                disabled={entitiesLoading || entities.length === 0}
              />
            </div>
          </div>

          {recent.length > 0 && (
            <div className="ibpw-recent">
              <p className="ibpw-recent__label">Recently used</p>
              <div className="ibpw-recent__row">
                {recent.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="ibpw-recent__chip"
                    title={name}
                    onClick={() => chooseEntity(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {entitiesLoading ? (
            <div className="ibpw-skel-list">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="ibpw-skel ibpw-skel-row" />
              ))}
            </div>
          ) : filteredEntities.length === 0 ? (
            <p className="ibpw-empty-note">No entities match “{entityFilter}”.</p>
          ) : (
            <ul className="ibpw-entity-list">
              {filteredEntities.map((e) => (
                <li key={e.name}>
                  <button
                    type="button"
                    className={`ibpw-entity ${selectedEntity === e.name ? "is-selected" : ""}`}
                    onClick={() => chooseEntity(e.name)}
                  >
                    <span className="ibpw-entity__name">{e.name}</span>
                    {e.entity_type && (
                      <span className="ibpw-entity__type">{e.entity_type}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* ---------------- CENTER: Columns + Live Preview ---------------- */}
      <div className="ibpw__col ibpw__col--center">
        {/* Column explorer */}
        <section className="ibpw-panel">
          <header className="ibpw-panel__head">
            <h4 className="ibpw-panel__title">Columns</h4>
            {selectableProps.length > 0 && (
              <span className="ibpw-badge ibpw-badge--accent">
                {orderedSelected.length} / {selectableProps.length}
              </span>
            )}
            <span className="ibpw-spacer" />
            <button
              type="button"
              className="ibpw-chip-btn"
              onClick={selectAll}
              disabled={selectableProps.length === 0}
            >
              Select all
            </button>
            <button
              type="button"
              className="ibpw-chip-btn"
              onClick={deselectAll}
              disabled={orderedSelected.length === 0}
            >
              Clear
            </button>
          </header>

          {!selectedEntity ? (
            <div className="ibpw-state">
              <span className="ibpw-state__icon">🗂️</span>
              <span className="ibpw-state__title">No entity selected</span>
              <span className="ibpw-state__desc">
                Pick an entity from the explorer to browse its columns.
              </span>
            </div>
          ) : entityLoading ? (
            <div className="ibpw-skel-list">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="ibpw-skel ibpw-skel-row" />
              ))}
            </div>
          ) : (
            <>
              <div className="ibpw-fields__toolbar">
                <div className="ibpw-search">
                  <span className="ibpw-search__icon">⌕</span>
                  <input
                    className="ibpw-input"
                    type="text"
                    placeholder="Search columns…"
                    value={propFilter}
                    onChange={(e) => setPropFilter(e.target.value)}
                  />
                </div>
              </div>
              <div className="ibpw-fields__grid">
                {filteredProps.map((p) => {
                  const checked = selected.includes(p.name);
                  return (
                    <label
                      key={p.name}
                      className={`ibpw-field ${checked ? "is-checked" : ""}`}
                      title={p.label || p.name}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleProp(p.name)}
                        style={{ display: "none" }}
                      />
                      <span className="ibpw-field__box">{checked ? "✓" : ""}</span>
                      <span className="ibpw-field__main">
                        <span className="ibpw-field__name">{p.name}</span>
                        <span className="ibpw-field__meta">
                          {p.role === "measure" && (
                            <span className="ibpw-badge ibpw-badge--kf">KF</span>
                          )}
                          {autoSelected.has(p.name) && (
                            <span
                              className="ibpw-badge ibpw-badge--accent"
                              title="Recommended for Transformation Discovery"
                            >
                              Recommended
                            </span>
                          )}
                          <span className="ibpw-type">
                            {String(p.type || "").replace(/^Edm\./, "")}
                          </span>
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </section>

        {/* Live preview grid */}
        <section className="ibpw-panel">
          <header className="ibpw-panel__head">
            <h4 className="ibpw-panel__title">Live Preview</h4>
            <span className="ibpw-spacer" />
            {previewStatus && (
              <span className={`ibpw-badge ibpw-badge--${previewStatus.cls}`}>
                <span className="ibpw-badge__dot" />
                {previewStatus.text}
              </span>
            )}
          </header>

          {previewLoading ? (
            <div className="ibpw-skel-grid">
              {Array.from({ length: 7 }).map((_, i) => (
                <div key={i} className="ibpw-skel ibpw-skel-grid__line" />
              ))}
            </div>
          ) : previewError ? (
            <div className="ibpw-state ibpw-state--error">
              <span className="ibpw-state__icon">⚠️</span>
              <span className="ibpw-state__title">Preview couldn’t load</span>
              <span className="ibpw-state__desc">{previewError}</span>
            </div>
          ) : !selectedEntity ? (
            <div className="ibpw-state">
              <span className="ibpw-state__icon">📊</span>
              <span className="ibpw-state__title">Nothing to preview yet</span>
              <span className="ibpw-state__desc">
                Select an entity and a few columns to see the first 10 rows.
              </span>
            </div>
          ) : orderedSelected.length === 0 ? (
            <div className="ibpw-state">
              <span className="ibpw-state__icon">✅</span>
              <span className="ibpw-state__title">Select at least one column</span>
              <span className="ibpw-state__desc">
                Choose columns above and the preview updates automatically.
              </span>
            </div>
          ) : previewRows.length === 0 ? (
            <div className="ibpw-state">
              <span className="ibpw-state__icon">🈳</span>
              <span className="ibpw-state__title">No rows returned</span>
              <span className="ibpw-state__desc">
                This selection returned no sample rows.
              </span>
            </div>
          ) : (
            <div className="ibpw-grid-wrap">
              <table className="ibpw-grid">
                <colgroup>
                  {previewCols.map((c) => (
                    <col key={c} style={{ width: colWidths[c] ?? DEFAULT_COL_WIDTH }} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    {previewCols.map((c) => {
                      const active = sort.col === c;
                      return (
                        <th key={c} style={{ position: "sticky" }}>
                          <div className="ibpw-grid__th-inner" onClick={() => toggleSort(c)}>
                            <span className="ibpw-grid__th-label" title={c}>
                              {c}
                            </span>
                            <span
                              className={`ibpw-grid__sort ${active ? "" : "ibpw-grid__sort--idle"}`}
                            >
                              {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
                            </span>
                          </div>
                          <span
                            className="ibpw-grid__resize"
                            onPointerDown={(e) => startResize(e, c)}
                          />
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((row, idx) => (
                    <tr key={idx}>
                      {previewCols.map((c) => (
                        <td
                          key={c}
                          className={looksNumeric(row[c]) ? "ibpw-grid__num" : ""}
                          title={row[c] != null ? String(row[c]) : ""}
                        >
                          {row[c] != null ? String(row[c]) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* ---------------- RIGHT: Dataset Summary ---------------- */}
      <div className="ibpw__col ibpw__col--right">
        <section className="ibpw-panel">
          <header className="ibpw-panel__head">
            <h4 className="ibpw-panel__title">Dataset Summary</h4>
          </header>
          <div className="ibpw-panel__body">
            <div className="ibpw-summary__stats">
              <div className="ibpw-stat">
                <span className="ibpw-stat__label">Entity</span>
                <span
                  className={`ibpw-stat__value ${selectedEntity ? "" : "ibpw-stat__value--muted"}`}
                  title={selectedEntity || undefined}
                >
                  {selectedEntity || "—"}
                </span>
              </div>
              <div className="ibpw-stat">
                <span className="ibpw-stat__label">Available columns</span>
                <span className="ibpw-stat__value">
                  {selectableProps.length || "—"}
                </span>
              </div>
              <div className="ibpw-stat">
                <span className="ibpw-stat__label">Selected columns</span>
                <span className="ibpw-stat__value">{orderedSelected.length || 0}</span>
              </div>
              <div className="ibpw-stat">
                <span className="ibpw-stat__label">Preview rows</span>
                <span className="ibpw-stat__value">
                  {previewRows.length || (selectedEntity ? 0 : "—")}
                </span>
              </div>
              <div className="ibpw-stat">
                <span className="ibpw-stat__label">Imported rows</span>
                <span
                  className={`ibpw-stat__value ${imported ? "" : "ibpw-stat__value--muted"}`}
                >
                  {imported ? importedCount?.toLocaleString?.() ?? importedCount : "Not yet"}
                </span>
              </div>
            </div>

            <div className={`ibpw-readiness ibpw-readiness--${readiness.cls}`}>
              <span className="ibpw-readiness__icon">{readiness.icon}</span>
              <span>{readiness.text}</span>
            </div>

            <button
              type="button"
              className="ibpw-btn"
              onClick={importDataset}
              disabled={fetching || orderedSelected.length === 0}
            >
              {fetching && <span className="ibpw-btn__spin" />}
              {fetching
                ? "Importing…"
                : imported
                  ? "Re-import dataset"
                  : "Import dataset"}
            </button>

            {imported && !fetching && (
              <p className="ibpw-summary__hint">
                Dataset ready — use <strong>Continue</strong> below to proceed.
              </p>
            )}

            {error && <p className="ibpw-summary__error">⚠️ {String(error)}</p>}
          </div>
        </section>
      </div>
    </div>
    </div>
  );
}

export default IbpDatasetWorkspace;
