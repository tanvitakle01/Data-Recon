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
  S4_TRANSFORMATION_DISCOVERY_FIELDS,
  recommendedFieldsFor,
} from "../lib/transformationDiscoveryFields";
import "./ibpWorkspace.css";
import "./s4Workspace.css";

// SAP S/4HANA dataset builder — a three-pane, metadata-driven workspace used in
// the wizard's connector step when SAP S/4HANA is selected. It discovers
// entities, relationships, and properties from $metadata, lets the user build a
// star join (primary + N related entities) with editable composite keys, live-
// previews the joined result, and imports the full joined dataset. The imported
// dataset is handed back via `onLoaded({columns,preview,rows,rowCount})` — the
// same contract SapFetchPanel uses — so it flows into mapping/reconciliation
// like any other dataset. No backend/data-flow behaviour is changed here.

const PREVIEW_DEBOUNCE_MS = 500;
const DEFAULT_COL_WIDTH = 150;

function looksNumeric(v) {
  if (v === null || v === undefined || v === "") return false;
  if (typeof v === "number") return true;
  const s = String(v).trim();
  return s !== "" && !Number.isNaN(Number(s));
}

const shortName = (e) => (e && e.startsWith("A_") ? e.slice(2) : e);

function S4DatasetWorkspace({ onLoaded, dataset, onStageChange }) {
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
  // entity/join/column workspace (Card 3), "preview" → imported dataset
  // preview only (Card 4). Initialized from `dataset` (not an effect) so a
  // returning user with an already-imported dataset lands straight on the
  // preview card with no flash of the earlier cards.
  const [stage, setStage] = useState(dataset ? "preview" : "connect");
  useEffect(() => {
    onStageChange?.(stage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  // ---- entities ----
  const [entities, setEntities] = useState([]);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [recent, setRecent] = useState([]);

  // ---- primary + joins ----
  const [primaryEntity, setPrimaryEntity] = useState("");
  const [primaryLoading, setPrimaryLoading] = useState(false);
  const [relationships, setRelationships] = useState([]);
  const [entityMeta, setEntityMeta] = useState({}); // entity -> {properties:[{name,type,is_key}], keys:[]}
  const [joins, setJoins] = useState([]); // [{entity, type, keys:[{left,right}]}]
  const [selectedByEntity, setSelectedByEntity] = useState({}); // entity -> [propName]
  // entity -> Set(propName) auto-checked by a Transformation Discovery rule
  // (e.g. selecting Material also checks MaterialGroup, ...), tracked
  // separately so the "Recommended" badge only marks the supporting fields,
  // not the trigger field itself, and clears once a field is deselected.
  const [autoSelectedByEntity, setAutoSelectedByEntity] = useState({});
  const [propFilter, setPropFilter] = useState("");

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
  const [importedPreview, setImportedPreview] = useState(
    dataset
      ? {
          columns: dataset.columns ?? [],
          rows: (dataset.preview ?? []).slice(0, 10),
          rowCount: dataset.rowCount ?? 0,
        }
      : null
  );
  const [error, setError] = useState(null);

  // ---- export (full dataset, exactly as received — not the 10-row preview) ----
  const [importedRows, setImportedRows] = useState(dataset?.rows ?? null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  const invalidate = () => setImported(false);

  // ---- Connect & load metadata (discover entities) ----
  // Triggered explicitly by the connect prompt / Refresh Metadata, not on
  // mount. `refresh` keeps the workspace visible (entity-list skeleton only)
  // instead of dropping back to the full-screen connecting state.
  const connect = useCallback(async ({ refresh = false } = {}) => {
    if (refresh) setRefreshing(true);
    else setConnState("connecting");
    setEntitiesLoading(true);
    setConnError(null);
    try {
      const res = await api.get("/api/connectors/s4/entities");
      const p = res.data ?? {};
      if (!p.success) {
        setConnError(p.error || "Failed to load S/4 entities");
        setConnState("error");
        return;
      }
      setEntities(p.entities ?? []);
      setConnState("connected");
    } catch (err) {
      setConnError(err?.message || String(err));
      setConnState("error");
    } finally {
      setEntitiesLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Reconnect: discard the loaded metadata/join spec and return to the
  // connect prompt for a clean start.
  const reconnect = useCallback(() => {
    setEntities([]);
    setPrimaryEntity("");
    setRelationships([]);
    setEntityMeta({});
    setJoins([]);
    setSelectedByEntity({});
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
    return entities.filter((e) => e.name.toLowerCase().includes(q));
  }, [entities, entityFilter]);

  // Fetch (and cache) an entity's properties + keys.
  const loadEntityMeta = async (entity) => {
    if (entityMeta[entity]) return entityMeta[entity];
    const res = await api.get(
      `/api/connectors/s4/entities/${encodeURIComponent(entity)}/properties`
    );
    const p = res.data ?? {};
    if (!p.success) throw new Error(p.error || `Failed to load properties for ${entity}`);
    const meta = { properties: p.properties ?? [], keys: p.keys ?? [] };
    setEntityMeta((prev) => ({ ...prev, [entity]: meta }));
    return meta;
  };

  const defaultProps = (meta, count, includeKeys) => {
    const keys = meta.keys;
    const nonKeys = meta.properties.filter((p) => !p.is_key).map((p) => p.name);
    return (includeKeys ? keys : []).concat(nonKeys.slice(0, count));
  };

  // ---- choose primary entity ----
  const choosePrimary = async (entity) => {
    setPrimaryEntity(entity);
    setJoins([]);
    setSelectedByEntity({});
    setAutoSelectedByEntity({});
    setRelationships([]);
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setSort({ col: null, dir: "asc" });
    setColWidths({});
    setImported(false);
    setError(null);
    if (!entity) return;

    setRecent((prev) => [entity, ...prev.filter((n) => n !== entity)].slice(0, 5));
    setPrimaryLoading(true);
    try {
      const [meta, relRes] = await Promise.all([
        loadEntityMeta(entity),
        api.get(`/api/connectors/s4/entities/${encodeURIComponent(entity)}/relationships`),
      ]);
      setSelectedByEntity({ [entity]: defaultProps(meta, 4, true) });
      const rp = relRes.data ?? {};
      setRelationships(rp.success ? rp.relationships ?? [] : []);
    } catch (err) {
      setError(`Failed to load entity metadata: ${err?.message || err}`);
    } finally {
      setPrimaryLoading(false);
    }
  };

  // ---- joins ----
  const joinedEntities = useMemo(() => joins.map((j) => j.entity), [joins]);

  const addJoin = async (rel) => {
    if (rel.target_entity === primaryEntity || joinedEntities.includes(rel.target_entity)) return;
    invalidate();
    try {
      const meta = await loadEntityMeta(rel.target_entity);
      setJoins((prev) => [
        ...prev,
        {
          entity: rel.target_entity,
          type: "left",
          keys: (rel.suggested_keys || []).map((k) => ({ left: k, right: k })),
        },
      ]);
      setSelectedByEntity((prev) => ({
        ...prev,
        [rel.target_entity]: defaultProps(meta, 3, false),
      }));
    } catch (err) {
      setError(`Failed to add join: ${err?.message || err}`);
    }
  };

  const removeJoin = (entity) => {
    invalidate();
    setJoins((prev) => prev.filter((j) => j.entity !== entity));
    setSelectedByEntity((prev) => {
      const next = { ...prev };
      delete next[entity];
      return next;
    });
    setAutoSelectedByEntity((prev) => {
      const next = { ...prev };
      delete next[entity];
      return next;
    });
  };

  const patchJoin = (entity, patch) => {
    invalidate();
    setJoins((prev) => prev.map((j) => (j.entity === entity ? { ...j, ...patch } : j)));
  };
  const setKeyPair = (entity, idx, side, value) =>
    patchJoin(
      entity,
      {
        keys: joins
          .find((j) => j.entity === entity)
          .keys.map((k, i) => (i === idx ? { ...k, [side]: value } : k)),
      }
    );
  const addKeyPair = (entity) => {
    const j = joins.find((x) => x.entity === entity);
    patchJoin(entity, { keys: [...j.keys, { left: "", right: "" }] });
  };
  const removeKeyPair = (entity, idx) => {
    const j = joins.find((x) => x.entity === entity);
    patchJoin(entity, { keys: j.keys.filter((_, i) => i !== idx) });
  };

  // ---- column selection ----
  // Checking a Transformation Discovery trigger field (e.g. Material,
  // ProductionPlant) also checks its supporting attributes within the same
  // entity, filtered to whatever actually exists there — missing ones are
  // skipped silently. The user can still deselect any of them individually.
  const toggleProp = (entity, name) => {
    invalidate();
    setSelectedByEntity((prev) => {
      const cur = prev[entity] || [];
      if (cur.includes(name)) {
        setAutoSelectedByEntity((autoPrev) => {
          const curAuto = autoPrev[entity];
          if (!curAuto?.has(name)) return autoPrev;
          const nextAuto = new Set(curAuto);
          nextAuto.delete(name);
          return { ...autoPrev, [entity]: nextAuto };
        });
        return { ...prev, [entity]: cur.filter((n) => n !== name) };
      }

      const availableNames = (entityMeta[entity]?.properties || []).map((p) => p.name);
      const recommended = recommendedFieldsFor(S4_TRANSFORMATION_DISCOVERY_FIELDS, name, availableNames);
      if (recommended.length === 0) return { ...prev, [entity]: [...cur, name] };

      const newlyAdded = recommended.filter((f) => f !== name && !cur.includes(f));
      if (newlyAdded.length > 0) {
        setAutoSelectedByEntity((autoPrev) => {
          const curAuto = autoPrev[entity] || new Set();
          return { ...autoPrev, [entity]: new Set([...curAuto, ...newlyAdded]) };
        });
      }
      return { ...prev, [entity]: Array.from(new Set([...cur, ...recommended])) };
    });
  };
  const selectGroup = (entity, all) => {
    invalidate();
    setSelectedByEntity((prev) => ({
      ...prev,
      [entity]: all ? (entityMeta[entity]?.properties || []).map((p) => p.name) : [],
    }));
    setAutoSelectedByEntity((prev) => ({ ...prev, [entity]: new Set() }));
  };

  const entitiesInPlay = useMemo(
    () => (primaryEntity ? [primaryEntity, ...joinedEntities] : []),
    [primaryEntity, joinedEntities]
  );

  const totalSelected = useMemo(
    () => entitiesInPlay.reduce((n, e) => n + (selectedByEntity[e]?.length || 0), 0),
    [entitiesInPlay, selectedByEntity]
  );
  const totalAvailable = useMemo(
    () => entitiesInPlay.reduce((n, e) => n + (entityMeta[e]?.properties.length || 0), 0),
    [entitiesInPlay, entityMeta]
  );

  const joinsValid = useMemo(
    () => joins.every((j) => j.keys.length > 0 && j.keys.every((k) => k.left && k.right)),
    [joins]
  );

  // ---- assembled join spec (sent to preview/fetch) ----
  const spec = useMemo(
    () => ({
      primary: { entity: primaryEntity, properties: selectedByEntity[primaryEntity] || [] },
      joins: joins.map((j) => ({
        entity: j.entity,
        properties: selectedByEntity[j.entity] || [],
        type: j.type,
        keys: j.keys,
      })),
    }),
    [primaryEntity, joins, selectedByEntity]
  );
  const specKey = useMemo(() => JSON.stringify(spec), [spec]);
  const canQuery = Boolean(primaryEntity) && totalSelected > 0 && joinsValid;

  // ---- live joined preview (debounced) ----
  const previewTimer = useRef(null);
  useEffect(() => {
    // Only fetch while Card 3 (Build Dataset) is actually visible — no point
    // refreshing a live preview the user can't see.
    if (!canQuery || stage !== "build") return undefined;
    let cancelled = false;
    clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(async () => {
      setPreviewLoading(true);
      setPreviewError(null);
      try {
        const res = await api.post("/api/connectors/s4/preview", spec);
        const p = res.data ?? {};
        if (cancelled) return;
        if (!p.success) {
          setPreviewError(p.error || "Preview failed");
          setPreviewRows([]);
          setPreviewCols([]);
          return;
        }
        setPreviewRows(p.rows ?? []);
        setPreviewCols(p.columns ?? []);
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
  }, [specKey, canQuery, stage]);

  // ---- grid: sort + resize ----
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
      prev.col === col ? { col, dir: prev.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" }
    );

  const resizeRef = useRef(null);
  const startResize = (e, col) => {
    e.preventDefault();
    e.stopPropagation();
    resizeRef.current = { col, startX: e.clientX, startW: colWidths[col] ?? DEFAULT_COL_WIDTH };
    const onMove = (ev) => {
      const r = resizeRef.current;
      if (!r) return;
      setColWidths((prev) => ({ ...prev, [r.col]: Math.max(70, r.startW + (ev.clientX - r.startX)) }));
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // ---- import ----
  const importDataset = async () => {
    if (!canQuery) return;
    setFetching(true);
    setError(null);
    try {
      const res = await api.post("/api/connectors/s4/fetch", spec);
      const p = res.data ?? {};
      if (!p.success) return setError(p.error || "Failed to fetch dataset");
      const rows = p.rows ?? [];
      const columns = p.columns ?? previewCols;
      setImported(true);
      setImportedCount(rows.length);
      setImportedPreview({ columns, rows: rows.slice(0, 10), rowCount: rows.length });
      setImportedRows(rows);
      setStage("preview");
      // Fields auto-checked by a Transformation Discovery rule (MDT/recommended
      // fields), flattened across every entity in play — carried along so
      // downstream mapping generation can exclude them while they remain
      // selectable here for tracking/validation.
      const mdtFields = Array.from(
        new Set(entitiesInPlay.flatMap((e) => Array.from(autoSelectedByEntity[e] || [])))
      );
      onLoaded?.({ columns, preview: rows.slice(0, 10), rows, rowCount: rows.length, mdtFields });
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
        sourceSystem: "S4",
        datasetName: shortName(primaryEntity),
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
    : !primaryEntity
      ? { cls: "wait", icon: "○", text: "Select a primary entity" }
      : !joinsValid
        ? { cls: "wait", icon: "○", text: "Complete join keys" }
        : totalSelected === 0
          ? { cls: "wait", icon: "○", text: "Select columns to import" }
          : { cls: "ready", icon: "◆", text: "Ready to import" };

  const previewStatus = previewLoading
    ? { cls: "amber", text: "Loading…" }
    : previewError
      ? { cls: "red", text: "Preview error" }
      : previewRows.length > 0
        ? { cls: "accent", text: `Live · ${previewRows.length} rows` }
        : null;

  const availableRelationships = relationships.filter(
    (r) => r.target_entity !== primaryEntity && !joinedEntities.includes(r.target_entity)
  );

  // ---- Connection gate: don't render the explorer until metadata loads ----
  if (connState === "idle") {
    return (
      <SapConnectPrompt
        serviceName="SAP S/4HANA"
        description="Connect to your SAP S/4HANA service to discover entities, relationships, and available fields."
        onConnect={() => connect()}
      />
    );
  }
  if (connState === "connecting") {
    return <SapConnecting serviceName="SAP S/4HANA" />;
  }
  if (connState === "error") {
    return (
      <SapConnectError
        serviceName="SAP S/4HANA"
        error={connError}
        onRetry={() => connect()}
      />
    );
  }

  // ---- Card 2: connected, not yet building — no entity browser yet ----
  if (stage === "connect") {
    return (
      <SapConnectedSummary
        serviceName="SAP S/4HANA"
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
  // clearing any entity/join/column selections (the workspace never unmounts).
  if (stage === "preview") {
    return (
      <div className="ibpw-root">
        {imported && importedPreview && importedPreview.rows.length > 0 && (
          <section className="ibpw-panel ibpw-imported">
            <header className="ibpw-panel__head">
              <h4 className="ibpw-panel__title">Imported Dataset Preview</h4>
              <span className="ibpw-spacer" />
              {primaryEntity && <span className="ibpw-badge ibpw-badge--count">{primaryEntity}</span>}
              <span className="ibpw-badge ibpw-badge--accent">{importedPreview.rowCount.toLocaleString()} rows</span>
              <span className="ibpw-badge ibpw-badge--count">{importedPreview.columns.length} cols</span>
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
                          <span className="ibpw-grid__th-label" title={c}>{c}</span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {importedPreview.rows.map((row, idx) => (
                    <tr key={idx}>
                      {importedPreview.columns.map((c) => (
                        <td key={c} className={looksNumeric(row[c]) ? "ibpw-grid__num" : ""} title={row[c] != null ? String(row[c]) : ""}>
                          {row[c] != null ? String(row[c]) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="ibpw-imported__caption">
              Showing {importedPreview.rows.length} of {importedPreview.rowCount.toLocaleString()} rows
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
            disabled={fetching || !canQuery}
          >
            {fetching && <span className="ibpw-btn__spin" />}
            {fetching ? "Importing…" : "Re-import Dataset"}
          </button>
        </div>
        {error && <p className="ibpw-summary__error">⚠️ {String(error)}</p>}
      </div>
    );
  }

  // ---- Card 3: Build Dataset — entity/join/column workspace ----
  return (
    <div className="ibpw-root">
      <SapConnectedBar
        entitiesCount={entities.length}
        propertiesCount={primaryEntity ? totalAvailable : null}
        onRefresh={() => connect({ refresh: true })}
        onReconnect={reconnect}
        refreshing={refreshing}
        showImport={false}
      />
      <div className="ibpw">
        {/* ---------------- LEFT: Entity + Relationship Explorer ---------------- */}
        <div className="ibpw__col ibpw__col--left">
          <section className="ibpw-panel">
            <header className="ibpw-panel__head">
              <h4 className="ibpw-panel__title">Entities</h4>
              <span className="ibpw-spacer" />
              {!entitiesLoading && <span className="ibpw-badge ibpw-badge--count">{entities.length}</span>}
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
                  {recent.map((n) => (
                    <button key={n} type="button" className="ibpw-recent__chip" title={n} onClick={() => choosePrimary(n)}>
                      {n}
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
            ) : (
              <ul className="ibpw-entity-list">
                {filteredEntities.map((e) => (
                  <li key={e.name}>
                    <button
                      type="button"
                      className={`ibpw-entity ${primaryEntity === e.name ? "is-selected" : ""}`}
                      onClick={() => choosePrimary(e.name)}
                    >
                      <span className="ibpw-entity__name">{e.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {/* Related entities → add as joins */}
            {primaryEntity && !primaryLoading && availableRelationships.length > 0 && (
              <div className="s4j-related">
                <p className="s4j-related__label">Related entities</p>
                {availableRelationships.map((r) => (
                  <button
                    key={r.nav}
                    type="button"
                    className="s4j-related__item"
                    onClick={() => addJoin(r)}
                    title={`Join keys: ${r.suggested_keys.join(", ") || "none — set manually"}`}
                  >
                    <span className="s4j-related__main">
                      <span className="s4j-related__name">{r.target_entity}</span>
                      <span className="s4j-related__keys">
                        {r.suggested_keys.join(" · ") || "set keys manually"}
                      </span>
                    </span>
                    <span className="ibpw-badge ibpw-badge--count">{r.cardinality}</span>
                    <span className="s4j-related__add">+</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* ---------------- CENTER: Join Builder + Columns + Preview ---------------- */}
        <div className="ibpw__col ibpw__col--center">
          {/* Join builder */}
          <section className="ibpw-panel">
            <header className="ibpw-panel__head">
              <h4 className="ibpw-panel__title">Join Builder</h4>
              <span className="ibpw-spacer" />
              {joins.length > 0 && (
                <span className="ibpw-badge ibpw-badge--accent">{joins.length} join{joins.length > 1 ? "s" : ""}</span>
              )}
            </header>

            {!primaryEntity ? (
              <div className="ibpw-state">
                <span className="ibpw-state__icon">🧩</span>
                <span className="ibpw-state__title">No primary entity</span>
                <span className="ibpw-state__desc">Pick a primary entity, then add related entities to join.</span>
              </div>
            ) : primaryLoading ? (
              <div className="ibpw-skel-list">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="ibpw-skel ibpw-skel-row" />
                ))}
              </div>
            ) : (
              <div className="s4j-builder">
                <div className="s4j-primary">
                  <span>Primary</span>
                  <span className="s4j-primary__chip">{primaryEntity}</span>
                </div>

                {joins.map((j) => {
                  const leftOpts = entityMeta[primaryEntity]?.properties.map((p) => p.name) || [];
                  const rightOpts = entityMeta[j.entity]?.properties.map((p) => p.name) || [];
                  return (
                    <div key={j.entity} className="s4j-join">
                      <div className="s4j-join__head">
                        <span className="s4j-join__name">{j.entity}</span>
                        <div className="s4j-toggle">
                          {["left", "inner"].map((t) => (
                            <button
                              key={t}
                              type="button"
                              className={`s4j-toggle__opt ${j.type === t ? "is-active" : ""}`}
                              onClick={() => patchJoin(j.entity, { type: t })}
                            >
                              {t === "left" ? "Left" : "Inner"}
                            </button>
                          ))}
                        </div>
                        <span className="ibpw-spacer" />
                        <button type="button" className="s4j-join__remove" title="Remove join" onClick={() => removeJoin(j.entity)}>
                          ✕
                        </button>
                      </div>

                      <div className="s4j-keys">
                        <span className="s4j-keys__label">Join keys (primary = {shortName(j.entity)})</span>
                        {j.keys.map((k, idx) => (
                          <div key={idx} className="s4j-keypair">
                            <select
                              className="s4j-select"
                              value={k.left}
                              onChange={(e) => setKeyPair(j.entity, idx, "left", e.target.value)}
                            >
                              <option value="">— primary key —</option>
                              {leftOpts.map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </select>
                            <span className="s4j-keypair__eq">=</span>
                            <select
                              className="s4j-select"
                              value={k.right}
                              onChange={(e) => setKeyPair(j.entity, idx, "right", e.target.value)}
                            >
                              <option value="">— joined key —</option>
                              {rightOpts.map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </select>
                            <button type="button" className="s4j-keypair__rm" title="Remove key" onClick={() => removeKeyPair(j.entity, idx)}>
                              ✕
                            </button>
                          </div>
                        ))}
                        <button type="button" className="s4j-keyadd" onClick={() => addKeyPair(j.entity)}>
                          + Add key
                        </button>
                      </div>
                    </div>
                  );
                })}

                {joins.length === 0 && (
                  <p className="ibpw-summary__hint" style={{ textAlign: "left", margin: 0 }}>
                    Add related entities from the left to build joins, or import the primary entity on its own.
                  </p>
                )}
              </div>
            )}
          </section>

          {/* Column explorer (grouped by entity) */}
          {primaryEntity && !primaryLoading && (
            <section className="ibpw-panel">
              <header className="ibpw-panel__head">
                <h4 className="ibpw-panel__title">Columns</h4>
                <span className="ibpw-badge ibpw-badge--accent">{totalSelected} / {totalAvailable}</span>
                <span className="ibpw-spacer" />
                <div className="ibpw-search" style={{ maxWidth: 220 }}>
                  <span className="ibpw-search__icon">⌕</span>
                  <input
                    className="ibpw-input"
                    type="text"
                    placeholder="Search columns…"
                    value={propFilter}
                    onChange={(e) => setPropFilter(e.target.value)}
                  />
                </div>
              </header>

              <div style={{ maxHeight: 260, overflowY: "auto" }}>
                {entitiesInPlay.map((entity) => {
                  const meta = entityMeta[entity];
                  if (!meta) return null;
                  const q = propFilter.trim().toLowerCase();
                  const props = q
                    ? meta.properties.filter((p) => p.name.toLowerCase().includes(q))
                    : meta.properties;
                  const sel = selectedByEntity[entity] || [];
                  return (
                    <div key={entity} className="s4j-group">
                      <div className="s4j-group__head">
                        <span className="s4j-group__name">{entity}</span>
                        <span className="s4j-group__role">{entity === primaryEntity ? "primary" : "joined"}</span>
                        <span className="ibpw-badge ibpw-badge--count">{sel.length}/{meta.properties.length}</span>
                        <span className="ibpw-spacer" />
                        <button type="button" className="ibpw-chip-btn" onClick={() => selectGroup(entity, true)}>All</button>
                        <button type="button" className="ibpw-chip-btn" onClick={() => selectGroup(entity, false)}>None</button>
                      </div>
                      <div className="ibpw-fields__grid" style={{ maxHeight: "none" }}>
                        {props.map((p) => {
                          const checked = sel.includes(p.name);
                          return (
                            <label key={p.name} className={`ibpw-field ${checked ? "is-checked" : ""}`} title={p.name}>
                              <input type="checkbox" checked={checked} onChange={() => toggleProp(entity, p.name)} style={{ display: "none" }} />
                              <span className="ibpw-field__box">{checked ? "✓" : ""}</span>
                              <span className="ibpw-field__main">
                                <span className="ibpw-field__name">{p.name}</span>
                                <span className="ibpw-field__meta">
                                  {p.is_key && <span className="ibpw-badge ibpw-badge--kf">KEY</span>}
                                  {autoSelectedByEntity[entity]?.has(p.name) && (
                                    <span
                                      className="ibpw-badge ibpw-badge--accent"
                                      title="Recommended for Transformation Discovery"
                                    >
                                      Recommended
                                    </span>
                                  )}
                                  <span className="ibpw-type">{String(p.type || "").replace(/^Edm\./, "")}</span>
                                </span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Live joined preview */}
          {primaryEntity && !primaryLoading && (
            <section className="ibpw-panel">
              <header className="ibpw-panel__head">
                <h4 className="ibpw-panel__title">Live Joined Preview</h4>
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
              ) : !canQuery ? (
                <div className="ibpw-state">
                  <span className="ibpw-state__icon">📊</span>
                  <span className="ibpw-state__title">Nothing to preview yet</span>
                  <span className="ibpw-state__desc">Select columns (and complete any join keys) to preview joined rows.</span>
                </div>
              ) : previewRows.length === 0 ? (
                <div className="ibpw-state">
                  <span className="ibpw-state__icon">🈳</span>
                  <span className="ibpw-state__title">No joined rows</span>
                  <span className="ibpw-state__desc">The sampled rows didn’t match on the join keys. Try Left join or different keys.</span>
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
                                <span className="ibpw-grid__th-label" title={c}>{c}</span>
                                <span className={`ibpw-grid__sort ${active ? "" : "ibpw-grid__sort--idle"}`}>
                                  {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
                                </span>
                              </div>
                              <span className="ibpw-grid__resize" onPointerDown={(e) => startResize(e, c)} />
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedRows.map((row, idx) => (
                        <tr key={idx}>
                          {previewCols.map((c) => (
                            <td key={c} className={looksNumeric(row[c]) ? "ibpw-grid__num" : ""} title={row[c] != null ? String(row[c]) : ""}>
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
          )}
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
                  <span className="ibpw-stat__label">Entities</span>
                  <span className={`ibpw-stat__value ${primaryEntity ? "" : "ibpw-stat__value--muted"}`}>
                    {entitiesInPlay.length || "—"}
                  </span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Primary</span>
                  <span className={`ibpw-stat__value ${primaryEntity ? "" : "ibpw-stat__value--muted"}`} title={primaryEntity || undefined}>
                    {primaryEntity || "—"}
                  </span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Joins</span>
                  <span className="ibpw-stat__value">
                    {joins.length ? joins.map((j) => `${j.type}`).join(", ") : "none"}
                  </span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Available columns</span>
                  <span className="ibpw-stat__value">{totalAvailable || "—"}</span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Selected columns</span>
                  <span className="ibpw-stat__value">{totalSelected || 0}</span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Preview rows</span>
                  <span className="ibpw-stat__value">{previewRows.length || (canQuery ? 0 : "—")}</span>
                </div>
                <div className="ibpw-stat">
                  <span className="ibpw-stat__label">Imported rows</span>
                  <span className={`ibpw-stat__value ${imported ? "" : "ibpw-stat__value--muted"}`}>
                    {imported ? importedCount?.toLocaleString?.() ?? importedCount : "Not yet"}
                  </span>
                </div>
              </div>

              <div className={`ibpw-readiness ibpw-readiness--${readiness.cls}`}>
                <span className="ibpw-readiness__icon">{readiness.icon}</span>
                <span>{readiness.text}</span>
              </div>

              <button type="button" className="ibpw-btn" onClick={importDataset} disabled={fetching || !canQuery}>
                {fetching && <span className="ibpw-btn__spin" />}
                {fetching ? "Importing…" : imported ? "Re-import dataset" : "Import dataset"}
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

export default S4DatasetWorkspace;
