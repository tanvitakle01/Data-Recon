import { useEffect, useMemo, useRef, useState } from "react";
import api from "../services/api";
import PreviewTable from "./PreviewTable";

// Metadata-driven SAP IBP dataset builder.
//
// Flow: discover entities from $metadata -> pick an entity -> choose
// properties -> preview 10 sample rows for the current selection -> fetch the
// full dataset with $select. Nothing here is hardcoded to a specific entity
// or column.
//
// IBP planning services reject a select-less read ("You must pass at least one
// attribute or key figure") and also expose properties that cannot be
// selected, so the flow is selection-driven: only `selectable` properties are
// offered, the preview always reflects the current selection, and the entity's
// server-provided default selection is applied on load so the preview isn't
// empty.
function IBPDatasetBuilder({ onDatasetLoaded }) {
  const [entities, setEntities] = useState([]);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [selectedEntity, setSelectedEntity] = useState("");

  const [properties, setProperties] = useState([]); // [{name, type, role, label, selectable}]
  const [selected, setSelected] = useState([]); // property names
  const [propFilter, setPropFilter] = useState("");
  const [entityLoading, setEntityLoading] = useState(false);

  const [previewRows, setPreviewRows] = useState([]);
  const [previewCols, setPreviewCols] = useState([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);

  const [fetching, setFetching] = useState(false);
  const [fetchedCount, setFetchedCount] = useState(null);
  const [error, setError] = useState(null);

  // ---- Step 1: discover entities ----------------------------------------
  useEffect(() => {
    let cancelled = false;

    const loadEntities = async () => {
      setEntitiesLoading(true);
      setError(null);
      try {
        const res = await api.get("/api/connectors/ibp/entities");
        const payload = res.data ?? {};
        if (!payload.success) {
          if (!cancelled) setError(payload.error || "Failed to load IBP entities");
          return;
        }
        if (!cancelled) setEntities(payload.entities ?? []);
      } catch (err) {
        if (!cancelled) setError(`Failed to load IBP entities: ${err?.message || err}`);
      } finally {
        if (!cancelled) setEntitiesLoading(false);
      }
    };

    loadEntities();
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredEntities = useMemo(() => {
    const q = entityFilter.trim().toLowerCase();
    if (!q) return entities;
    return entities.filter(
      (e) =>
        e.name.toLowerCase().includes(q) ||
        (e.entity_type || "").toLowerCase().includes(q)
    );
  }, [entities, entityFilter]);

  // Only selectable properties can be fetched, so that's all we offer.
  const selectableProps = useMemo(
    () => properties.filter((p) => p.selectable),
    [properties]
  );

  // ---- Step 2: load properties + default selection for chosen entity ----
  const chooseEntity = async (entityName) => {
    setSelectedEntity(entityName);
    setProperties([]);
    setSelected([]);
    setPropFilter("");
    setPreviewRows([]);
    setPreviewCols([]);
    setPreviewError(null);
    setFetchedCount(null);
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

      const selectable = new Set(props.filter((p) => p.selectable).map((p) => p.name));
      const defaults = (payload.default_properties ?? []).filter((n) => selectable.has(n));
      setSelected(defaults);
    } catch (err) {
      setError(`Failed to load entity metadata: ${err?.message || err}`);
    } finally {
      setEntityLoading(false);
    }
  };

  // ---- Step 3: property selection ---------------------------------------
  const filteredProps = useMemo(() => {
    const q = propFilter.trim().toLowerCase();
    if (!q) return selectableProps;
    return selectableProps.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.label || "").toLowerCase().includes(q)
    );
  }, [selectableProps, propFilter]);

  const toggleProp = (name) => {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  };

  const selectAll = () => setSelected(selectableProps.map((p) => p.name));
  const deselectAll = () => setSelected([]);

  // Preserve metadata order for selected columns.
  const orderedSelected = useMemo(
    () => selectableProps.map((p) => p.name).filter((n) => selected.includes(n)),
    [selectableProps, selected]
  );

  // ---- Live preview: re-fetch (debounced) whenever selection changes ----
  const previewKey = useMemo(
    () => `${selectedEntity}::${orderedSelected.join(",")}`,
    [selectedEntity, orderedSelected]
  );
  const previewTimer = useRef(null);

  useEffect(() => {
    // Nothing to preview without a selection; the render gates on
    // `orderedSelected.length` so any prior preview is hidden (and a fresh
    // entity resets it in chooseEntity) — no synchronous clear needed here.
    if (!selectedEntity || orderedSelected.length === 0) {
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
    }, 450);

    return () => {
      cancelled = true;
      clearTimeout(previewTimer.current);
    };
    // previewKey captures entity + ordered selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  // ---- Step 4: fetch full dataset ---------------------------------------
  const fetchDataset = async () => {
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

      setFetchedCount(rows.length);

      onDatasetLoaded?.({
        rows: rows.length,
        columns,
        preview: rows.slice(0, 10),
        data: rows,
      });
    } catch (err) {
      setError(`Failed to fetch dataset: ${err?.message || err}`);
    } finally {
      setFetching(false);
    }
  };

  return (
    <div>
      {/* Entity selection */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 480 }}>
        <label style={{ fontWeight: 700, fontSize: 13, color: "#334155" }}>
          {entitiesLoading ? "Loading IBP entities…" : "Select an entity"}
        </label>

        <input
          type="text"
          value={entityFilter}
          placeholder="Search entities…"
          onChange={(e) => setEntityFilter(e.target.value)}
          disabled={entitiesLoading || entities.length === 0}
          style={inputStyle}
        />

        <select
          value={selectedEntity}
          onChange={(e) => chooseEntity(e.target.value)}
          disabled={entitiesLoading || entities.length === 0}
          size={Math.min(8, Math.max(3, filteredEntities.length))}
          style={{ ...inputStyle, height: "auto" }}
        >
          {filteredEntities.map((e) => (
            <option key={e.name} value={e.name}>
              {e.name}
              {e.entity_type ? `  ·  ${e.entity_type}` : ""}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div style={{ marginTop: 12, color: "#b91c1c", whiteSpace: "pre-wrap", fontSize: 12 }}>
          ⚠️ {String(error)}
        </div>
      )}

      {entityLoading && (
        <div style={{ marginTop: 12, color: "#64748b" }}>Loading properties…</div>
      )}

      {/* Property selection + live preview */}
      {selectedEntity && !entityLoading && selectableProps.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            <span style={{ fontWeight: 800, color: "#0f172a" }}>Select Columns</span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 800,
                background: "rgba(59,130,246,0.12)",
                color: "#1d4ed8",
                borderRadius: 999,
                padding: "3px 10px",
              }}
            >
              {orderedSelected.length} of {selectableProps.length} selected
            </span>
            <button className="btn-secondary" type="button" onClick={selectAll}>
              Select All
            </button>
            <button className="btn-secondary" type="button" onClick={deselectAll}>
              Deselect All
            </button>
          </div>

          <input
            type="text"
            value={propFilter}
            placeholder="Search properties…"
            onChange={(e) => setPropFilter(e.target.value)}
            style={{ ...inputStyle, maxWidth: 320, marginBottom: 10 }}
          />

          <div
            className="surface-elevated"
            style={{
              maxHeight: 220,
              overflow: "auto",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: 4,
              padding: 10,
            }}
          >
            {filteredProps.map((p) => (
              <label
                key={p.name}
                title={p.label || p.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                  padding: "2px 4px",
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(p.name)}
                  onChange={() => toggleProp(p.name)}
                />
                <span style={{ fontWeight: 600 }}>{p.name}</span>
                {p.role === "measure" && (
                  <span style={{ color: "#0d9488", fontSize: 10, fontWeight: 800 }}>KF</span>
                )}
                <span style={{ color: "#94a3b8", fontSize: 11 }}>{p.type}</span>
              </label>
            ))}
          </div>

          {previewError && (
            <div style={{ marginTop: 12, color: "#b45309", whiteSpace: "pre-wrap", fontSize: 12 }}>
              ⚠️ {String(previewError)}
            </div>
          )}

          {previewLoading && (
            <div style={{ marginTop: 10, color: "#64748b", fontSize: 13 }}>
              Loading preview…
            </div>
          )}

          {!previewLoading && !previewError && orderedSelected.length > 0 && previewRows.length > 0 && (
            <PreviewTable
              data={{ columns: previewCols, preview: previewRows }}
              title={`${selectedEntity} preview (first ${previewRows.length} rows)`}
            />
          )}

          {!previewLoading && orderedSelected.length === 0 && (
            <div style={{ marginTop: 10, color: "#64748b", fontSize: 13 }}>
              Select at least one column to preview.
            </div>
          )}

          <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12 }}>
            <button
              className="btn-primary"
              type="button"
              onClick={fetchDataset}
              disabled={fetching || orderedSelected.length === 0}
            >
              {fetching ? "Fetching dataset…" : "Continue — Fetch Dataset"}
            </button>

            {fetchedCount != null && (
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  background: "rgba(16,185,129,0.12)",
                  color: "#047857",
                  borderRadius: 999,
                  padding: "4px 12px",
                }}
              >
                IBP loaded · {fetchedCount} rows · {orderedSelected.length} cols
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const inputStyle = {
  padding: "8px 10px",
  borderRadius: 10,
  border: "1px solid #cbd5e1",
  fontSize: 13,
  outline: "none",
};

export default IBPDatasetBuilder;
