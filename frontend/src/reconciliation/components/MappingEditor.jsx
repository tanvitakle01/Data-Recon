const KEY_ROLE = "🔑 Key";
const COMPARE_ROLE = "📊 Compare";

function isKeyRole(role) {
  return /key/i.test(String(role));
}

// Rebuilds the backend `mapping` object (key_fields / compare_fields) from the
// current, possibly hand-edited, display rows so /reconcile stays in sync with
// what the analyst sees.
function rebuildMapping(display, options) {
  const key_fields = [];
  const compare_fields = [];
  for (const row of display) {
    const pair = { source_col: row.source_col, target_col: row.target_col };
    if (isKeyRole(row.role)) key_fields.push(pair);
    else compare_fields.push(pair);
  }
  return { key_fields, compare_fields, options: options ?? { case_insensitive: true, trim_whitespace: true } };
}

function MappingEditor({ mapping, targetColumns, loading, error, onChange, onRegenerate }) {
  const display = mapping?.display ?? [];
  const options = mapping?.mapping?.options;

  const updateRow = (index, patch) => {
    const nextDisplay = display.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange({ display: nextDisplay, mapping: rebuildMapping(nextDisplay, options) });
  };

  return (
    <div className="mapping-editor">
      <div className="mapping-editor__head">
        <p className="wizard-field__help">
          Suggested source-to-target mappings. Adjust the target column or role for any row.
        </p>
        <button
          type="button"
          className="wizard-btn wizard-btn--ghost"
          onClick={onRegenerate}
          disabled={loading}
        >
          {loading ? "Mapping…" : "Regenerate auto-mapping"}
        </button>
      </div>

      {error && <p className="wizard-step__error">{error}</p>}
      {loading && !display.length && <p className="wizard-step__hint">Detecting column mapping…</p>}

      {display.length > 0 && (
        <div className="surface-elevated mapping-editor__table-wrap">
          <table className="table-elevated mapping-editor__table">
            <thead>
              <tr>
                <th>Logical Field</th>
                <th>Source Field</th>
                <th>Target Field</th>
                <th>Mapping Type</th>
              </tr>
            </thead>
            <tbody>
              {display.map((row, index) => (
                <tr key={`${row.source_col}-${index}`}>
                  <td className="mapping-editor__logical">{row.logical}</td>
                  <td>{row.source_col}</td>
                  <td>
                    <select
                      className="wizard-select wizard-select--sm"
                      value={row.target_col ?? ""}
                      onChange={(e) => updateRow(index, { target_col: e.target.value })}
                    >
                      <option value="">— none —</option>
                      {targetColumns.map((col) => (
                        <option key={col} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      className="wizard-select wizard-select--sm"
                      value={isKeyRole(row.role) ? "key" : "compare"}
                      onChange={(e) =>
                        updateRow(index, { role: e.target.value === "key" ? KEY_ROLE : COMPARE_ROLE })
                      }
                    >
                      <option value="key">🔑 Key</option>
                      <option value="compare">📊 Compare</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default MappingEditor;
