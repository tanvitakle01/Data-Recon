import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import {
  SapConnecting,
  SapConnectError,
  SapConnectedBar,
} from "./SapConnectionGate";
import JoinCanvas from "./JoinCanvas";
import {
  IBP_TRANSFORMATION_DISCOVERY_FIELDS,
  recommendedFieldsFor,
  withAuxiliaryFields,
} from "../lib/transformationDiscoveryFields";
import { matchProposedToSchema } from "../lib/fieldMatching";
import "./ibpWorkspace.css";

// SAP IBP dataset workspace — a three-pane data-exploration surface used in
// the wizard's Step 3 (Target) when the IBP connector is selected.
//
// The layout is the shared, de-cluttered JoinCanvas (see JoinCanvas.jsx):
// two collapsible inputs (entity + field), a single entity node card on the
// canvas (IBP has no joins), and a result-preview grid with a slim import bar.
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

function IbpDatasetWorkspace({
  onLoaded,
  dataset,
  onStageChange,
  onOpenDetailedPreview,
  preselectFields = [],
  prepopulate = null,
}) {
  // ---- connection stage ----
  // Metadata is fetched automatically on mount — once the user confirms the
  // SAP IBP connector there is no separate "Connect & Load Metadata" click.
  // "connecting" → skeletons, "error" → retry card, "connected" → the
  // workspace. Everyone (fresh or returning) starts in the connecting state so
  // they see loading skeletons, never a flash of an empty/prompt screen, while
  // the connect-on-mount effect discovers entities.
  const [connState, setConnState] = useState("connecting");
  const [connError, setConnError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // ---- card stage (progressive disclosure within the workspace) ----
  // "connect" → still connecting/loading metadata (drives the sub-stage pill),
  // "build" → the full entity/column workspace (Card 3). There is no longer a
  // "Connected → Continue to Build Dataset" stopping point: connect() flips
  // straight to "build" on success, so a successful connection lands the user
  // directly in the workspace. The imported data grid is not a stage here — it
  // lives on a dedicated preview page. A returning user with an already-imported
  // dataset starts on "build" (with "Open Detailed Preview" available).
  const [stage, setStage] = useState(dataset ? "build" : "connect");
  useEffect(() => {
    onStageChange?.(stage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  // ---- entities ----
  const [entities, setEntities] = useState([]);
  // Entity (re)load flag — the connect/refresh spinner is surfaced by
  // SapConnectedBar's `refreshing`, so only the setter is needed here.
  const [, setEntitiesLoading] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [selectedEntity, setSelectedEntity] = useState("");

  // ---- canvas UI (collapsible inputs; purely presentational) ----
  const [entityListOpen, setEntityListOpen] = useState(false);
  const [fieldListOpen, setFieldListOpen] = useState(false);

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
  // Sheet-proposed fields that don't exist on the chosen entity's live schema.
  // Tracking preserved (setter still used); the surfacing note was retired with
  // the old Columns panel, so only the setter is kept.
  const [, setPreselectUnmatched] = useState([]);

  // Plain-language note describing what the sheet / Step-1 instruction
  // pre-placed on the canvas (and anything it named that couldn't be used).
  const [prepopNote, setPrepopNote] = useState(null);

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
      // Metadata loaded — go straight to the Build Dataset workspace. No
      // intermediate "Continue to Build Dataset" confirmation.
      setStage("build");
    } catch (err) {
      setConnError(err?.message || String(err));
      setConnState("error");
    } finally {
      setEntitiesLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Reconnect: discard the loaded metadata/selection and immediately
  // re-establish the connection from scratch. connect() drops the workspace
  // into the connecting (skeleton) state and flips back to "build" on success,
  // so there is no separate connect prompt to click through.
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
    setStage("connect");
    connect();
  }, [connect]);

  // Connect + discover metadata automatically as soon as the workspace mounts
  // (i.e. right after the user confirms the SAP IBP connector). Applies to both
  // a fresh selection and a returning user navigating back into the step —
  // either way the explorer is never left empty and no manual connect click is
  // required.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    // Run-once fetch-on-mount; connect() already set the connecting state.
    connect();
  }, [connect]);

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
    setPreselectUnmatched([]);
    setPropFilter("");
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setSort({ col: null, dir: "asc" });
    setColWidths({});
    setImported(false);
    setError(null);

    if (!entityName) return;

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
      const selectableNames = props.filter((p) => p.selectable).map((p) => p.name);
      // Sheet-driven pre-selection ONLY: pre-check the proposed fields that
      // actually exist on this entity (validated against the live schema). There
      // is NO default/fallback selection — with no uploaded mapping sheet, or a
      // sheet that proposed nothing matching this entity, nothing is
      // auto-selected and the user picks columns explicitly. Unmatched proposals
      // are surfaced, never invented.
      let base = [];
      if (preselectFields.length > 0) {
        const { matched, unmatched } = matchProposedToSchema(preselectFields, selectableNames);
        setPreselectUnmatched(unmatched);
        base = matched;
      }
      // Widen with MDT auxiliary evidence fields (PRODDESC / PRODGROUP / LOCNAME
      // / …) for each trigger field present, tracked in autoSelected so they
      // flow through the mdtFields boundary — fetched + previewed + fed to the
      // deterministic matcher, but excluded from the field mapping /
      // reconciliation output.
      const { selection, autoAdded } = withAuxiliaryFields(
        IBP_TRANSFORMATION_DISCOVERY_FIELDS,
        base,
        selectableNames
      );
      setSelected(selection);
      setAutoSelected(autoAdded);
    } catch (err) {
      setError(`Failed to load entity metadata: ${err?.message || err}`);
    } finally {
      setEntityLoading(false);
    }
  }, [preselectFields]);

  // ---- Canvas pre-population (mapping sheet / Step-1 instruction) ----
  // IBP is single-entity here, so this only ever selects the primary entity —
  // the backend gate already reduced an IBP side to one entity and dropped any
  // join details. Pre-population only: the entity and its column selection stay
  // fully editable, and nothing is fetched until the user imports.
  const prepopRef = useRef(null);
  const prepopKey = prepopulate ? JSON.stringify(prepopulate) : null;
  useEffect(() => {
    if (!prepopKey || connState !== "connected" || entities.length === 0) return undefined;
    // Already-imported dataset → don't reset the user's built side.
    if (dataset) return undefined;
    // Apply any one instruction exactly once, so clearing the pre-placed entity
    // doesn't fight this effect and get it re-selected.
    if (prepopRef.current === prepopKey) return undefined;
    prepopRef.current = prepopKey;

    let cancelled = false;
    (async () => {
      const { entities: wanted, unresolved, origin } = prepopulate;
      const from = origin === "freeText" ? "your entity/join instruction" : "your mapping sheet";
      const missing =
        unresolved.length > 0
          ? ` ${unresolved.join(", ")} ${unresolved.length > 1 ? "aren't" : "isn't"} available in this connector — pick the entity yourself.`
          : "";

      if (wanted.length === 0) {
        if (missing && !cancelled) {
          setPrepopNote(`Nothing could be pre-placed from ${from}.${missing}`);
        }
        return;
      }
      if (cancelled) return;
      setPrepopNote(
        `Pre-placed ${wanted[0]} from ${from}.${missing} Review and adjust anything below before importing.`
      );
      await chooseEntity(wanted[0]);
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prepopKey, connState, entities.length, dataset]);

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
      // Stay on the Build card after import; the full data grid now lives on a
      // dedicated preview page opened via "Open Detailed Preview".
      // Fields auto-checked by a Transformation Discovery rule (MDT/recommended
      // fields) — carried along so downstream mapping generation can exclude
      // them while they remain selectable here for tracking/validation. The
      // dataset (rows, preview, columns) is persisted to wizard state, which is
      // what the detailed-preview page reads.
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

  const readiness = imported
    ? { cls: "done", icon: "✓", text: `Dataset imported · ${importedCount ?? 0} rows` }
    : orderedSelected.length > 0 && !previewError
      ? { cls: "ready", icon: "◆", text: "Ready to import" }
      : { cls: "wait", icon: "○", text: "Select columns to import" };

  // ---- Canvas view-model: IBP is single-entity (no joins), so the canvas
  // holds exactly one node card. Field checkboxes, KF (measure) tags, and the
  // recommended tag map straight from the existing selection state; no field
  // reads a ref, so the handlers wire through unchanged. ----
  const canvasNodes = selectedEntity
    ? [
        {
          entity: selectedEntity,
          role: "primary",
          fields: selectableProps.map((p) => ({
            name: p.name,
            type: p.type,
            isKey: false,
            checked: selected.includes(p.name),
            recommended: autoSelected.has(p.name),
            measure: p.role === "measure",
          })),
          onToggleField: (name) => toggleProp(name),
          onSelectAll: selectAll,
          onClear: deselectAll,
          removable: false,
        },
      ]
    : [];

  // ---- Connection gate: show loading/error surfaces until metadata loads ----
  // Metadata loads automatically on mount, so there is no idle "Connect" prompt
  // and no "Connected → Continue to Build Dataset" confirmation. A successful
  // connect() flips straight to the Build Dataset workspace below.
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

  // ---- Build Dataset — entity/column workspace ----
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
      {prepopNote && (
        <p className="ibpw-prepop-note">
          ✨ {prepopNote}
          <button type="button" className="ibpw-prepop-note__dismiss" onClick={() => setPrepopNote(null)}>
            Dismiss
          </button>
        </p>
      )}
      <JoinCanvas
        serviceName="SAP IBP"
        joinsEnabled={false}
        entities={filteredEntities}
        activeEntity={selectedEntity}
        entityFilter={entityFilter}
        onEntityFilterChange={setEntityFilter}
        entityListOpen={entityListOpen}
        onToggleEntityList={() => setEntityListOpen((o) => !o)}
        onAddEntity={(name) => {
          setEntityListOpen(false);
          setEntityFilter("");
          chooseEntity(name);
        }}
        fieldFilter={propFilter}
        onFieldFilterChange={setPropFilter}
        fieldListOpen={fieldListOpen}
        onToggleFieldList={() => setFieldListOpen((o) => !o)}
        nodes={canvasNodes}
        nodesLoading={entityLoading}
        preview={{
          rows: sortedRows,
          cols: previewCols,
          loading: previewLoading,
          error: previewError,
          colWidths,
          sort,
          onToggleSort: toggleSort,
          onStartResize: startResize,
          defaultColWidth: DEFAULT_COL_WIDTH,
        }}
        readiness={readiness}
        canImport={Boolean(selectedEntity) && orderedSelected.length > 0}
        importing={fetching}
        imported={imported}
        onImport={importDataset}
        onOpenDetailedPreview={onOpenDetailedPreview}
      />
      {error && (
        <p className="ibpw-summary__error" style={{ marginTop: 12 }}>
          ⚠️ {String(error)}
        </p>
      )}
    </div>
  );
}

export default IbpDatasetWorkspace;
