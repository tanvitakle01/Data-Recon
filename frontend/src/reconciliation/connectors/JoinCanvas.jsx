import { useState } from "react";
import "./joinCanvas.css";

// Reusable, presentational Join Builder layout shared by the SAP S/4HANA and
// SAP IBP dataset workspaces. It owns NO connector knowledge, NO data fetching,
// and NO entity source of its own — every entity, field, join, and handler is
// passed in by the parent workspace, which remains the owner of all state,
// endpoints, and join/preview/import logic. Instantiated once per connector
// (one S4 instance, one IBP instance), each scoped to its own `entities` list,
// so one connector's picker can never surface another connector's entities.
//
// Layout (Recon-Studio style):
//   • Toolbar   — two collapsible inputs: Entity (add/browse) and Field
//                 (manual override; secondary, collapsed by default).
//   • Canvas    — entity node cards (fields with checkboxes, key/recommended
//                 tags) connected by a line + join-type/key-count badge; the
//                 badge opens a join-config popover (type, keys, cardinality).
//   • Preview   — result grid (row count + sample rows) with a slim action bar
//                 (readiness, Import dataset, Open Detailed Preview).
//
// `joinsEnabled={false}` renders single-node mode (IBP): exactly one node card,
// no connector lines, no relationship affordances.

// The allow-listed join types, shared by the badge and the config toggle. Kept
// in lockstep with the backend allow-list (entity_join_parser.JOIN_TYPES) so a
// pre-populated join type is always one the canvas can display and edit.
const JOIN_TYPES = ["inner", "left", "right", "full"];

function looksNumeric(v) {
  if (v === null || v === undefined || v === "") return false;
  if (typeof v === "number") return true;
  const s = String(v).trim();
  return s !== "" && !Number.isNaN(Number(s));
}

// A single field row inside a node card. Key fields are excluded from the
// dataset by default (they're join plumbing, not reconciliation data) but the
// checkbox is an ordinary, interactive toggle — the user can select one in or
// deselect it like any other field. The KEY tag itself is also a button: any
// field can be explicitly marked/unmarked as a key, independent of whether
// it's selected into the dataset.
function FieldRow({ field, onToggle, onToggleKey }) {
  const { name, type, isKey, checked, recommended, measure } = field;
  const typeLabel = type && <span className="jc-field__type">{String(type).replace(/^Edm\./, "")}</span>;

  return (
    <label className={`jc-field ${checked ? "is-checked" : ""}`} title={isKey ? `${name} (key)` : name}>
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(name)}
        style={{ display: "none" }}
      />
      <span className="jc-field__box">{checked ? "✓" : ""}</span>
      <span className="jc-field__name">{name}</span>
      <span className="jc-field__meta">
        {/* onToggleKey is opt-in per workspace — connectors with no key
            concept (e.g. IBP, single-entity) simply don't pass it. */}
        {onToggleKey && (
          <button
            type="button"
            className={`jc-tag jc-tag--key${isKey ? "" : " jc-tag--key-off"}`}
            onClick={() => onToggleKey(name)}
            title={isKey ? "Remove key designation" : "Mark as key"}
          >
            {isKey ? "🔑 KEY" : "+ KEY"}
          </button>
        )}
        {measure && <span className="jc-tag jc-tag--kf">KF</span>}
        {recommended && (
          <span className="jc-tag jc-tag--rec" title="Recommended for Transformation Discovery">
            Recommended
          </span>
        )}
        {typeLabel}
      </span>
    </label>
  );
}

// One entity node card: header (name, role, remove) + searchable field list.
function NodeCard({ node, fieldFilter, showRole = true }) {
  const {
    entity,
    role,
    fields = [],
    onToggleField,
    onToggleKey,
    onSelectAll,
    onClear,
    removable,
    onRemove,
  } = node;
  const q = (fieldFilter || "").trim().toLowerCase();
  const shown = q ? fields.filter((f) => f.name.toLowerCase().includes(q)) : fields;
  const selectedCount = fields.filter((f) => f.checked).length;
  return (
    <div className={`jc-node jc-node--${role}`}>
      <header className="jc-node__head">
        <span className="jc-node__name" title={entity}>
          {entity}
        </span>
        {showRole && <span className={`jc-node__role jc-node__role--${role}`}>{role}</span>}
        <span className="jc-spacer" />
        <span className="jc-node__count">
          {selectedCount}/{fields.length}
        </span>
        {removable && (
          <button
            type="button"
            className="jc-node__remove"
            title="Remove entity"
            onClick={() => onRemove?.(entity)}
          >
            ✕
          </button>
        )}
      </header>
      <div className="jc-node__actions">
        <button type="button" className="jc-chip-btn" onClick={onSelectAll}>
          All
        </button>
        <button type="button" className="jc-chip-btn" onClick={onClear}>
          None
        </button>
      </div>
      <div className="jc-node__fields">
        {shown.length === 0 ? (
          <p className="jc-node__empty">
            {q ? `No fields match “${fieldFilter}”.` : "No fields available."}
          </p>
        ) : (
          shown.map((f) => (
            <FieldRow key={f.name} field={f} onToggle={onToggleField} onToggleKey={onToggleKey} />
          ))
        )}
      </div>
    </div>
  );
}

// The line + centered badge between the primary and a joined node. Clicking the
// badge toggles a config popover (join type, match keys, cardinality, remove).
function JoinConnector({ join, open, onToggleOpen }) {
  const {
    toEntity,
    type,
    keys = [],
    cardinality,
    leftOptions = [],
    rightOptions = [],
    onSetType,
    onSetKey,
    onAddKey,
    onRemoveKey,
    onRemove,
  } = join;
  const keyCount = keys.length;
  return (
    <div className="jc-connector">
      <span className="jc-connector__line" />
      <button
        type="button"
        className={`jc-badge ${open ? "is-open" : ""}`}
        onClick={onToggleOpen}
        title="Configure join"
      >
        <span className="jc-badge__type">{(JOIN_TYPES.includes(type) ? type : "left").toUpperCase()}</span>
        <span className="jc-badge__sep">·</span>
        <span className="jc-badge__keys">
          {keyCount} {keyCount === 1 ? "key" : "keys"}
        </span>
      </button>
      <span className="jc-connector__line" />

      {open && (
        <div className="jc-config" role="dialog">
          <div className="jc-config__row">
            <span className="jc-config__label">Join type</span>
            <div className="jc-toggle">
              {JOIN_TYPES.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`jc-toggle__opt ${type === t ? "is-active" : ""}`}
                  onClick={() => onSetType(t)}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="jc-config__row">
            <span className="jc-config__label">Cardinality</span>
            <span className="jc-config__value">{cardinality || "—"}</span>
          </div>

          <div className="jc-config__keys">
            <span className="jc-config__label">Match keys</span>
            {keys.map((k, idx) => (
              <div key={idx} className="jc-keypair">
                <select
                  className="jc-select"
                  value={k.left}
                  onChange={(e) => onSetKey(idx, "left", e.target.value)}
                >
                  <option value="">— primary key —</option>
                  {leftOptions.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
                <span className="jc-keypair__eq">=</span>
                <select
                  className="jc-select"
                  value={k.right}
                  onChange={(e) => onSetKey(idx, "right", e.target.value)}
                >
                  <option value="">— {toEntity} key —</option>
                  {rightOptions.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="jc-keypair__rm"
                  title="Remove key"
                  onClick={() => onRemoveKey(idx)}
                >
                  ✕
                </button>
              </div>
            ))}
            <button type="button" className="jc-keyadd" onClick={onAddKey}>
              + Add key
            </button>
          </div>

          <button
            type="button"
            className="jc-config__remove"
            onClick={() => onRemove?.(toEntity)}
          >
            Remove join
          </button>
        </div>
      )}
    </div>
  );
}

export default function JoinCanvas({
  serviceName,
  joinsEnabled = true,
  // ---- entity input ----
  entities = [],
  activeEntity = "",
  entityFilter = "",
  onEntityFilterChange,
  entityListOpen = false,
  onToggleEntityList,
  onAddEntity,
  // ---- field input ----
  fieldFilter = "",
  onFieldFilterChange,
  fieldListOpen = false,
  onToggleFieldList,
  // ---- canvas ----
  nodes = [],
  nodesLoading = false,
  joins = [],
  relationships = [],
  onAddJoin,
  // ---- result preview ----
  preview = {},
  // ---- action bar ----
  readiness,
  canImport = false,
  importing = false,
  imported = false,
  onImport,
  onOpenDetailedPreview,
}) {
  const [openJoin, setOpenJoin] = useState(null); // entity name of open config
  const {
    rows = [],
    cols = [],
    loading: previewLoading = false,
    error: previewError = null,
    colWidths = {},
    sort = { col: null, dir: "asc" },
    onToggleSort,
    onStartResize,
    defaultColWidth = 150,
  } = preview;

  // The parent owns entity filtering (each connector filters differently), so
  // `entities` arrives already filtered by `entityFilter`. We only decide when
  // to reveal the browse dropdown: on explicit toggle, or as soon as the user
  // starts typing a query.
  const typing = (entityFilter || "").trim().length > 0;

  const primaryNode = nodes[0];
  const joinedNodes = nodes.slice(1);
  const joinFor = (entity) => joins.find((j) => j.toEntity === entity);

  return (
    <div className="jc">
      {/* ---------------- Toolbar: two collapsible inputs ---------------- */}
      <div className="jc-toolbar">
        {/* Entity input */}
        <div className="jc-input-group">
          <div className="jc-input">
            <span className="jc-input__icon">⌕</span>
            <input
              className="jc-input__field"
              type="text"
              placeholder={`Add an entity from ${serviceName}…`}
              value={entityFilter}
              onChange={(e) => onEntityFilterChange?.(e.target.value)}
              disabled={entities.length === 0}
            />
            <button
              type="button"
              className={`jc-input__toggle ${entityListOpen ? "is-open" : ""}`}
              onClick={onToggleEntityList}
              title={entityListOpen ? "Collapse entity list" : "Browse all entities"}
              aria-expanded={entityListOpen}
            >
              ▸
            </button>
          </div>
          {(entityListOpen || typing) && (
            <ul className="jc-dropdown">
              {entities.length === 0 ? (
                <li className="jc-dropdown__empty">
                  {typing ? `No entities match “${entityFilter}”.` : "No entities."}
                </li>
              ) : (
                entities.map((e) => (
                  <li key={e.name}>
                    <button
                      type="button"
                      className={`jc-dropdown__item ${activeEntity === e.name ? "is-active" : ""}`}
                      onClick={() => onAddEntity?.(e.name)}
                    >
                      <span className="jc-dropdown__name">{e.name}</span>
                      {e.entity_type && (
                        <span className="jc-dropdown__type">{e.entity_type}</span>
                      )}
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>

        {/* Field input (secondary, manual override) */}
        <div className="jc-input-group jc-input-group--secondary">
          <div className="jc-input jc-input--secondary">
            <span className="jc-input__icon">⌕</span>
            <input
              className="jc-input__field"
              type="text"
              placeholder="Adjust a field (usually auto-filled)…"
              value={fieldFilter}
              onChange={(e) => onFieldFilterChange?.(e.target.value)}
              onFocus={() => !fieldListOpen && onToggleFieldList?.()}
            />
            <button
              type="button"
              className={`jc-input__toggle ${fieldListOpen ? "is-open" : ""}`}
              onClick={onToggleFieldList}
              title={fieldListOpen ? "Collapse" : "Expand field search"}
              aria-expanded={fieldListOpen}
            >
              ▸
            </button>
          </div>
          <p className="jc-input__hint">
            Fields are populated automatically from your mapping sheet — use this only to
            adjust selections on a placed entity.
          </p>
        </div>
      </div>

      {/* ---------------- Canvas ---------------- */}
      <div className="jc-canvas">
        {nodesLoading ? (
          <div className="jc-skel">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="jc-skel__row" />
            ))}
          </div>
        ) : nodes.length === 0 ? (
          <div className="jc-empty">
            <span className="jc-empty__icon">🧩</span>
            <span className="jc-empty__title">Add an entity to begin</span>
            <span className="jc-empty__desc">
              Use the entity input above to place {joinsEnabled ? "a primary entity" : "an entity"}{" "}
              on the canvas.
            </span>
          </div>
        ) : (
          <div className="jc-flow">
            {primaryNode && (
              <NodeCard
                node={primaryNode}
                fieldFilter={fieldListOpen ? fieldFilter : ""}
                showRole={joinsEnabled}
              />
            )}

            {joinsEnabled &&
              joinedNodes.map((node) => {
                const join = joinFor(node.entity);
                return (
                  <div key={node.entity} className="jc-flow__seg">
                    {join && (
                      <JoinConnector
                        join={join}
                        open={openJoin === node.entity}
                        onToggleOpen={() =>
                          setOpenJoin((cur) => (cur === node.entity ? null : node.entity))
                        }
                      />
                    )}
                    <NodeCard node={node} fieldFilter={fieldListOpen ? fieldFilter : ""} />
                  </div>
                );
              })}

            {/* Add-related-entity affordance (S4 only) */}
            {joinsEnabled && primaryNode && relationships.length > 0 && (
              <div className="jc-flow__seg">
                <span className="jc-connector__line jc-connector__line--ghost" />
                <div className="jc-addjoin">
                  <span className="jc-addjoin__title">Add related entity</span>
                  <div className="jc-addjoin__list">
                    {relationships.map((r) => (
                      <button
                        key={r.nav}
                        type="button"
                        className="jc-addjoin__item"
                        onClick={() => onAddJoin?.(r)}
                        title={`Join keys: ${r.suggested_keys?.join(", ") || "set manually"}`}
                      >
                        <span className="jc-addjoin__name">{r.target_entity}</span>
                        <span className="jc-addjoin__keys">
                          {r.suggested_keys?.join(" · ") || "set keys manually"}
                        </span>
                        <span className="jc-addjoin__card">{r.cardinality}</span>
                        <span className="jc-addjoin__plus">+</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ---------------- Result preview + slim action bar ---------------- */}
      <div className="jc-preview">
        <header className="jc-preview__head">
          <h4 className="jc-preview__title">Result Preview</h4>
          {rows.length > 0 && !previewLoading && (
            <span className="jc-preview__count">{rows.length} sample rows</span>
          )}
          <span className="jc-spacer" />
          {readiness && (
            <span className={`jc-readiness jc-readiness--${readiness.cls}`}>
              <span className="jc-readiness__icon">{readiness.icon}</span>
              {readiness.text}
            </span>
          )}
          {imported && (
            <button
              type="button"
              className="jc-btn jc-btn--ghost"
              onClick={() => onOpenDetailedPreview?.()}
            >
              Open Detailed Preview
            </button>
          )}
          <button
            type="button"
            className="jc-btn jc-btn--primary"
            onClick={onImport}
            disabled={!canImport || importing}
          >
            {importing && <span className="jc-btn__spin" />}
            {importing ? "Importing…" : imported ? "Re-import dataset" : "Import dataset"}
          </button>
        </header>

        {previewLoading ? (
          <div className="jc-skel">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="jc-skel__row" />
            ))}
          </div>
        ) : previewError ? (
          <div className="jc-empty jc-empty--error">
            <span className="jc-empty__icon">⚠️</span>
            <span className="jc-empty__title">Preview couldn’t load</span>
            <span className="jc-empty__desc">{previewError}</span>
          </div>
        ) : rows.length === 0 ? (
          <div className="jc-empty">
            <span className="jc-empty__icon">📊</span>
            <span className="jc-empty__title">Nothing to preview yet</span>
            <span className="jc-empty__desc">
              Place an entity and select a few fields to see sample rows.
            </span>
          </div>
        ) : (
          <div className="jc-grid-wrap">
            <table className="jc-grid">
              <colgroup>
                {cols.map((c) => (
                  <col key={c} style={{ width: colWidths[c] ?? defaultColWidth }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  {cols.map((c) => {
                    const active = sort.col === c;
                    return (
                      <th key={c}>
                        <div className="jc-grid__th" onClick={() => onToggleSort?.(c)}>
                          <span className="jc-grid__th-label" title={c}>
                            {c}
                          </span>
                          <span className={`jc-grid__sort ${active ? "" : "is-idle"}`}>
                            {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
                          </span>
                        </div>
                        <span
                          className="jc-grid__resize"
                          onPointerDown={(e) => onStartResize?.(e, c)}
                        />
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={idx}>
                    {cols.map((c) => (
                      <td
                        key={c}
                        className={looksNumeric(row[c]) ? "jc-grid__num" : ""}
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
      </div>
    </div>
  );
}
