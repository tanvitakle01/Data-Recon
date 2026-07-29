import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";
import {
  SapConnecting,
  SapConnectError,
  SapConnectedBar,
} from "./SapConnectionGate";
import JoinCanvas from "./JoinCanvas";
import {
  S4_TRANSFORMATION_DISCOVERY_FIELDS,
  recommendedFieldsFor,
  withAuxiliaryFields,
} from "../lib/transformationDiscoveryFields";
import { matchProposedToSchema } from "../lib/fieldMatching";
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

// Keep only key pairs whose fields exist on both entities' live schemas. Used
// for join keys that came from a mapping sheet / typed instruction: the entity
// names were existence-gated server-side, and the key fields get the same
// treatment here, where the live property lists are known.
function validateKeyPairs(pairs, leftMeta, rightMeta) {
  if (!Array.isArray(pairs) || pairs.length === 0) return { valid: [], dropped: [] };
  const leftNames = new Set((leftMeta?.properties || []).map((p) => p.name));
  const rightNames = new Set((rightMeta?.properties || []).map((p) => p.name));
  const valid = [];
  const dropped = [];
  for (const pair of pairs) {
    const left = String(pair?.left ?? "").trim();
    const right = String(pair?.right ?? "").trim();
    if (left && right && leftNames.has(left) && rightNames.has(right)) {
      valid.push({ left, right });
    } else if (left || right) {
      dropped.push(left === right ? left : `${left || "?"} = ${right || "?"}`);
    }
  }
  return { valid, dropped };
}

function S4DatasetWorkspace({
  onLoaded,
  dataset,
  onStageChange,
  onOpenDetailedPreview,
  preselectFields = [],
  prepopulate = null,
}) {
  // ---- connection stage ----
  // Metadata is fetched automatically on mount — once the user confirms the
  // SAP S/4HANA connector there is no separate "Connect & Load Metadata" click.
  // "connecting" → skeletons, "error" → retry card, "connected" → the
  // workspace. Everyone (fresh or returning) starts in the connecting state so
  // they see loading skeletons, never a flash of an empty/prompt screen, while
  // the connect-on-mount effect discovers entities and relationships.
  const [connState, setConnState] = useState("connecting");
  const [connError, setConnError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // ---- card stage (progressive disclosure within the workspace) ----
  // "connect" → still connecting/loading metadata (drives the sub-stage pill),
  // "build" → the full entity/join/column workspace (Card 3). There is no
  // longer a "Connected → Continue to Build Dataset" stopping point: connect()
  // flips straight to "build" on success, so a successful connection lands the
  // user directly in the Join Builder. The imported data grid is not a stage
  // here — it lives on a dedicated preview page. A returning user with an
  // already-imported dataset starts on "build" (with "Open Detailed Preview").
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

  // ---- canvas UI (collapsible inputs; purely presentational) ----
  const [entityListOpen, setEntityListOpen] = useState(false);
  const [fieldListOpen, setFieldListOpen] = useState(false);

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
  // entity -> Set(propName) currently designated a KEY (shown with a KEY tag
  // and excluded from the dataset by default). Seeded from the entity's own
  // OData keys + this join's predicate keys when the entity/join is added,
  // but from then on it's fully user-owned — the KEY tag is a toggle button,
  // so any field can be marked/unmarked as a key regardless of its SAP
  // metadata origin.
  const [keyFieldsByEntity, setKeyFieldsByEntity] = useState({});
  const [propFilter, setPropFilter] = useState("");
  // Proposals already auto-selected by a match scan — so a join-driven re-scan
  // only auto-selects fields it NEWLY resolved, and never re-adds a field the
  // user has since manually deselected. (preselectUnmatched itself is derived
  // below, not stored.)
  const matchScanRef = useRef(new Set());

  // Plain-language note describing what the sheet / Step-1 instruction
  // pre-placed on the canvas (and anything it named that couldn't be used), so
  // the pre-population is visible rather than silent.
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
      // Metadata loaded — go straight to the Build Dataset (Join Builder)
      // screen. No intermediate "Continue to Build Dataset" confirmation.
      setStage("build");
    } catch (err) {
      setConnError(err?.message || String(err));
      setConnState("error");
    } finally {
      setEntitiesLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Reconnect: discard the loaded metadata/join spec and immediately
  // re-establish the connection from scratch. connect() drops the workspace
  // into the connecting (skeleton) state and flips back to "build" on success,
  // so there is no separate connect prompt to click through.
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
    setStage("connect");
    connect();
  }, [connect]);

  // Connect + discover metadata automatically as soon as the workspace mounts
  // (i.e. right after the user confirms the SAP S/4HANA connector). Applies to
  // both a fresh selection and a returning user navigating back into the step —
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

  // ---- choose primary entity ----
  // Returns `{ meta, relationships }` for the chosen entity so a caller that
  // needs to act on them immediately (canvas pre-population, which adds joins
  // right after) can use the freshly-loaded values instead of the state it just
  // set, which isn't readable until the next render.
  const choosePrimary = async (entity) => {
    setPrimaryEntity(entity);
    setJoins([]);
    setSelectedByEntity({});
    setAutoSelectedByEntity({});
    setKeyFieldsByEntity({});
    setRelationships([]);
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setSort({ col: null, dir: "asc" });
    setColWidths({});
    setImported(false);
    setError(null);
    if (!entity) return { meta: null, relationships: [] };

    setPrimaryLoading(true);
    try {
      const [meta, relRes] = await Promise.all([
        loadEntityMeta(entity),
        api.get(`/api/connectors/s4/entities/${encodeURIComponent(entity)}/relationships`),
      ]);
      // Sheet-driven pre-selection ONLY: pre-check the proposed fields that
      // actually exist here (validated against the live schema). There is NO
      // default/fallback selection — with no uploaded mapping sheet, or a sheet
      // that proposed nothing matching this entity, nothing is auto-selected and
      // the user picks columns explicitly. (S/4 TABLE-FIELD forms like VBAP-MATNR
      // frequently won't match OData semantic names; unmatched proposals are
      // surfaced rather than guessed.) Entity keys are NEVER seeded into the
      // dataset selection here — they're join plumbing, not reconciliation
      // data, so they default to excluded (Fix 1). They're still tagged KEY
      // and individually toggleable, in or out, like any other field.
      const propNames = meta.properties.map((p) => p.name);
      let primarySelection = [];
      if (preselectFields.length > 0) {
        const { matched } = matchProposedToSchema(preselectFields, propNames);
        // Seed the scan tracker so a later join re-scan treats these as
        // already-resolved (won't re-add them if the user deselects them).
        matchScanRef.current = new Set(matched);
        primarySelection = matched;
      } else {
        matchScanRef.current = new Set();
      }
      // Drop any structural key (entity key) that slipped into the base
      // selection, and seed this entity's KEY tags from its own OData keys
      // (join-predicate keys are added later, per join, in addJoin).
      const keyNames = new Set(meta.properties.filter((p) => p.is_key).map((p) => p.name));
      for (const k of meta.keys || []) keyNames.add(k);
      primarySelection = primarySelection.filter((n) => !keyNames.has(n));
      setKeyFieldsByEntity({ [entity]: keyNames });

      // Widen with MDT auxiliary evidence fields: for each trigger field present
      // (Material / ProductionPlant), auto-add its supporting attributes that
      // exist here, tracked in autoSelectedByEntity so they flow through the
      // mdtFields boundary — fetched + previewed + fed to the deterministic
      // matcher, but excluded from the field mapping / reconciliation output.
      const { selection, autoAdded } = withAuxiliaryFields(
        S4_TRANSFORMATION_DISCOVERY_FIELDS,
        primarySelection,
        propNames
      );
      setSelectedByEntity({ [entity]: selection });
      setAutoSelectedByEntity({ [entity]: autoAdded });
      const rp = relRes.data ?? {};
      const rels = rp.success ? rp.relationships ?? [] : [];
      setRelationships(rels);
      return { meta, relationships: rels };
    } catch (err) {
      setError(`Failed to load entity metadata: ${err?.message || err}`);
      return { meta: null, relationships: [] };
    } finally {
      setPrimaryLoading(false);
    }
  };

  // ---- joins ----
  const joinedEntities = useMemo(() => joins.map((j) => j.entity), [joins]);

  // Every selectable DATA column for this entity — i.e. every property that
  // isn't currently tagged KEY (`keyFieldsByEntity`). Keys default out of the
  // dataset (they're join plumbing, not reconciliation data), but the KEY tag
  // itself is a user toggle (see `toggleKeyField`), so this set — and
  // therefore what "Select All"/"Clear All" cover — changes as the user
  // marks/unmarks fields as keys.
  const dataFieldNames = useCallback(
    (entity) => {
      const excluded = keyFieldsByEntity[entity] ?? new Set();
      return (entityMeta[entity]?.properties || [])
        .map((p) => p.name)
        .filter((n) => !excluded.has(n));
    },
    [keyFieldsByEntity, entityMeta]
  );

  // Mark/unmark a field as a KEY. Marking a field as key also removes it from
  // the dataset selection — keys aren't included in the output by default,
  // even if the user had it checked in as a plain data column a moment ago.
  // Unmarking has no side effect on selection (a demoted field just becomes
  // an ordinary field, defaulting to whatever it already was).
  const toggleKeyField = (entity, name) => {
    invalidate();
    setKeyFieldsByEntity((prev) => {
      const cur = new Set(prev[entity] || []);
      if (cur.has(name)) {
        cur.delete(name);
      } else {
        cur.add(name);
        setSelectedByEntity((selPrev) => {
          const selCur = selPrev[entity] || [];
          if (!selCur.includes(name)) return selPrev;
          return { ...selPrev, [entity]: selCur.filter((n) => n !== name) };
        });
      }
      return { ...prev, [entity]: cur };
    });
  };

  // `overrides` lets a sheet-derived / typed instruction pre-place a join
  // (see the pre-population effect). It changes ONLY what was actually stated:
  // an unstated type or key set falls through to this function's existing
  // default — left join, keys mirrored from the relationship's suggested keys —
  // so there is exactly one default policy, and it lives here.
  // `primary`/`primaryMeta` let a caller pass the primary it just chose, whose
  // state isn't readable yet on this tick.
  const addJoin = async (rel, { type, keys, primary, primaryMeta } = {}) => {
    const primaryName = primary ?? primaryEntity;
    if (!rel?.target_entity || rel.target_entity === primaryName) return;
    if (joinedEntities.includes(rel.target_entity)) return;
    invalidate();
    try {
      const meta = await loadEntityMeta(rel.target_entity);
      const leftMeta = primaryMeta ?? entityMeta[primaryName];
      const defaultKeys = (rel.suggested_keys || []).map((k) => ({ left: k, right: k }));
      // Stated keys must name fields that actually exist on both entities —
      // same "validate, never invent" rule the entity names went through. Any
      // that don't are dropped (and reported), and if nothing survives we fall
      // back to the canvas default rather than inventing a predicate.
      const { valid, dropped } = validateKeyPairs(keys, leftMeta, meta);
      if (dropped.length > 0) {
        setPrepopNote((prev) =>
          [prev, `Ignored join key${dropped.length > 1 ? "s" : ""} ${dropped.join(", ")} — not a field on both entities.`]
            .filter(Boolean)
            .join(" ")
        );
      }
      const joinKeys = valid.length > 0 ? valid : defaultKeys;
      const suggestedKeys = new Set(joinKeys.map((k) => k.right));
      setJoins((prev) =>
        prev.some((j) => j.entity === rel.target_entity)
          ? prev
          : [
              ...prev,
              {
                entity: rel.target_entity,
                type: type ?? "left",
                keys: joinKeys,
              },
            ]
      );

      // A3: re-scan the sheet's proposed fields against this newly-joined
      // entity's schema (excluding the join-key fields, A1). Any proposal that
      // was unmatched against the primary alone but exists here is auto-selected
      // on this entity now — matchScanRef guards against re-adding one the user
      // already deselected. A2: everything else on a joined entity starts
      // unchecked but selectable.
      const dataNames = meta.properties
        .map((p) => p.name)
        .filter((n) => !suggestedKeys.has(n));
      const { matched } = matchProposedToSchema(preselectFields, dataNames);
      const newly = matched.filter((n) => !matchScanRef.current.has(n));
      matchScanRef.current = new Set([...matchScanRef.current, ...matched]);
      setSelectedByEntity((prev) => ({
        ...prev,
        [rel.target_entity]: newly,
      }));

      // Seed this entity's KEY tags from its own OData keys + this join's
      // right-side predicate keys; extend the primary's KEY tags with this
      // join's left-side predicate keys (a plain FK column on the primary may
      // not itself be a declared entity key). None of this touches the
      // dataset selection above — keys default to excluded either way.
      const targetKeyNames = new Set(meta.properties.filter((p) => p.is_key).map((p) => p.name));
      for (const k of meta.keys || []) targetKeyNames.add(k);
      for (const k of suggestedKeys) targetKeyNames.add(k);
      setKeyFieldsByEntity((prev) => ({
        ...prev,
        [rel.target_entity]: targetKeyNames,
        [primaryName]: new Set([...(prev[primaryName] || []), ...joinKeys.map((k) => k.left)]),
      }));
    } catch (err) {
      setError(`Failed to add join: ${err?.message || err}`);
    }
  };

  const removeJoin = (entity) => {
    invalidate();
    // Dropping an entity narrows the schema — forget any proposals that were
    // resolved via it so a later re-join can auto-select them again (A3).
    const removedNames = new Set((entityMeta[entity]?.properties || []).map((p) => p.name));
    matchScanRef.current = new Set(
      [...matchScanRef.current].filter((n) => !removedNames.has(n))
    );
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
    setKeyFieldsByEntity((prev) => {
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

  // ---- Canvas pre-population (mapping sheet / Step-1 instruction) ----
  // Places the entities that side's instruction named, and the join between
  // them, so the user reviews a filled-in canvas instead of an empty one. This
  // PRE-POPULATES, it does not bypass: everything placed here is ordinary
  // canvas state — editable, removable, and nothing is fetched until the user
  // imports. Entity names arrive already existence-gated server-side; join
  // type/keys are only ever overrides, with addJoin's default filling the rest.
  const prepopRef = useRef(null);
  const prepopKey = prepopulate ? JSON.stringify(prepopulate) : null;
  useEffect(() => {
    if (!prepopKey || connState !== "connected" || entities.length === 0) return undefined;
    // A dataset is already imported → the user has built this side. Re-placing
    // entities would silently reset their import.
    if (dataset) return undefined;
    // Apply any one instruction exactly once, so removing a pre-placed entity
    // doesn't fight this effect and get it re-added.
    if (prepopRef.current === prepopKey) return undefined;
    prepopRef.current = prepopKey;

    let cancelled = false;
    (async () => {
      const { entities: wanted, joinType, keys, unresolved, origin } = prepopulate;
      const from = origin === "freeText" ? "your entity/join instruction" : "your mapping sheet";
      const missing =
        unresolved.length > 0
          ? ` ${unresolved.join(", ")} ${unresolved.length > 1 ? "aren't" : "isn't"} available in this connector — add ${unresolved.length > 1 ? "them" : "it"} yourself.`
          : "";

      if (wanted.length === 0) {
        if (missing) setPrepopNote(`Nothing could be pre-placed from ${from}.${missing}`);
        return;
      }

      const joined = wanted.slice(1);
      const note = [
        `Pre-placed ${wanted.join(" + ")} from ${from}.`,
        joined.length > 0
          ? `Join type: ${joinType ?? "left (this canvas's default)"}.`
          : "",
        missing,
        "Review and adjust anything below before importing.",
      ]
        .filter(Boolean)
        .join(" ");
      setPrepopNote(note);

      const { meta, relationships: rels } = await choosePrimary(wanted[0]);
      if (cancelled || !meta) return;

      // Stated keys describe ONE join predicate, so they're only applied when a
      // single entity is being joined; with several, each join takes its own
      // relationship's suggested keys (the canvas default) instead of having one
      // stated pair mis-assigned to all of them.
      const keysFor = joined.length === 1 ? keys : null;
      for (const name of joined) {
        if (cancelled) return;
        const rel =
          rels.find((r) => r.target_entity === name) ?? { target_entity: name, suggested_keys: [] };
        await addJoin(rel, {
          type: joinType ?? undefined,
          keys: keysFor,
          primary: wanted[0],
          primaryMeta: meta,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prepopKey, connState, entities.length, dataset]);

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
    // "All" selects only real data fields — keys are excluded (Fix 1).
    setSelectedByEntity((prev) => ({
      ...prev,
      [entity]: all ? dataFieldNames(entity) : [],
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
    () => entitiesInPlay.reduce((n, e) => n + dataFieldNames(e).length, 0),
    [entitiesInPlay, dataFieldNames]
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
      // Stay on the Build card after import; the full data grid now lives on a
      // dedicated preview page opened via "Open Detailed Preview".
      // Fields auto-checked by a Transformation Discovery rule (MDT/recommended
      // fields), flattened across every entity in play — carried along so
      // downstream mapping generation can exclude them while they remain
      // selectable here for tracking/validation. The dataset (rows, preview,
      // columns) is persisted to wizard state, which is what the
      // detailed-preview page reads.
      const mdtFields = Array.from(
        new Set(entitiesInPlay.flatMap((e) => Array.from(autoSelectedByEntity[e] || [])))
      );
      onLoaded?.({
        columns,
        preview: rows.slice(0, 10),
        rows,
        rowCount: rows.length,
        mdtFields,
      });
    } catch (err) {
      setError(`Failed to fetch dataset: ${err?.message || err}`);
    } finally {
      setFetching(false);
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

  const availableRelationships = relationships.filter(
    (r) => r.target_entity !== primaryEntity && !joinedEntities.includes(r.target_entity)
  );

  // ---- Canvas view-model (presentational mapping of existing state) ----
  // Node cards: primary + each joined entity. Fields tagged KEY default out of
  // the dataset selection; the tag itself is a toggle button (onToggleKey), so
  // any field can be marked/unmarked as a key regardless of its SAP metadata
  // origin, independent of its checkbox (data-selection) state.
  const canvasNodes = (primaryEntity ? [primaryEntity, ...joinedEntities] : []).map(
    (entity, i) => {
      const role = i === 0 ? "primary" : "joined";
      const meta = entityMeta[entity];
      const keySet = keyFieldsByEntity[entity] ?? new Set();
      const sel = selectedByEntity[entity] || [];
      const auto = autoSelectedByEntity[entity];
      const fields = (meta?.properties || []).map((p) => ({
        name: p.name,
        type: p.type,
        isKey: keySet.has(p.name),
        checked: sel.includes(p.name),
        recommended: auto?.has(p.name) || false,
      }));
      return {
        entity,
        role,
        fields,
        onToggleField: (name) => toggleProp(entity, name),
        onToggleKey: (name) => toggleKeyField(entity, name),
        onSelectAll: () => selectGroup(entity, true),
        onClear: () => selectGroup(entity, false),
        removable: role === "joined",
        // JoinCanvas invokes this only from an event handler (onRemove(entity));
        // removeJoin reads matchScanRef there, never during render.
        // eslint-disable-next-line react-hooks/refs
        onRemove: removeJoin,
      };
    }
  );

  // Join connectors: each joined entity's type/keys/cardinality, wired to the
  // existing join-config handlers (patchJoin / setKeyPair / add / remove).
  const canvasJoins = joins.map((j) => {
    const rel = relationships.find((r) => r.target_entity === j.entity);
    return {
      toEntity: j.entity,
      type: j.type,
      keys: j.keys,
      cardinality: rel?.cardinality,
      leftOptions: entityMeta[primaryEntity]?.properties.map((p) => p.name) || [],
      rightOptions: entityMeta[j.entity]?.properties.map((p) => p.name) || [],
      onSetType: (t) => patchJoin(j.entity, { type: t }),
      onSetKey: (idx, side, value) => setKeyPair(j.entity, idx, side, value),
      onAddKey: () => addKeyPair(j.entity),
      onRemoveKey: (idx) => removeKeyPair(j.entity, idx),
      // Bare reference; JoinCanvas invokes it as onRemove(toEntity).
      onRemove: removeJoin,
    };
  });

  // ---- Connection gate: show loading/error surfaces until metadata loads ----
  // Metadata loads automatically on mount, so there is no idle "Connect" prompt
  // and no "Connected → Continue to Build Dataset" confirmation. A successful
  // connect() flips straight to the Build Dataset workspace below.
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

  // ---- Build Dataset — entity/join/column workspace ----
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
      {prepopNote && (
        <p className="ibpw-prepop-note">
          ✨ {prepopNote}
          <button type="button" className="ibpw-prepop-note__dismiss" onClick={() => setPrepopNote(null)}>
            Dismiss
          </button>
        </p>
      )}
      <JoinCanvas
        serviceName="SAP S/4HANA"
        joinsEnabled
        entities={filteredEntities}
        activeEntity={primaryEntity}
        entityFilter={entityFilter}
        onEntityFilterChange={setEntityFilter}
        entityListOpen={entityListOpen}
        onToggleEntityList={() => setEntityListOpen((o) => !o)}
        onAddEntity={(name) => {
          setEntityListOpen(false);
          setEntityFilter("");
          choosePrimary(name);
        }}
        fieldFilter={propFilter}
        onFieldFilterChange={setPropFilter}
        fieldListOpen={fieldListOpen}
        onToggleFieldList={() => setFieldListOpen((o) => !o)}
        nodes={canvasNodes}
        nodesLoading={primaryLoading}
        joins={canvasJoins}
        relationships={availableRelationships}
        onAddJoin={addJoin}
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
        canImport={canQuery}
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

export default S4DatasetWorkspace;
