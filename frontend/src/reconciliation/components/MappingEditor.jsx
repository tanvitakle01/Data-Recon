import { isKeyRole, isUserRow, rebuildMapping } from "../lib/payload";
import { Button, Select, Badge } from "@bristlecone/canopy";

const KEY_ROLE = "🔑 Key";
const COMPARE_ROLE = "📊 Compare";

// Per-row origin badge (the "Origin" column). Library/Groq/OpenAI are the
// generated tiers; user-added/user-edited are the manual tier.
const ORIGIN_BADGE = {
  library: { label: "Vector Library", variant: "info" },
  groq: { label: "Groq", variant: "default" },
  openai: { label: "OpenAI", variant: "default" },
  generated: { label: "Generated", variant: "default" },
  "user-added": { label: "Manual · added", variant: "success" },
  "user-edited": { label: "Manual · edited", variant: "warning" },
};

function MappingEditor({
  mapping,
  sourceColumns = [],
  targetColumns,
  loading,
  error,
  notice,
  onChange,
  onRegenerate,
}) {
  const display = mapping?.display ?? [];
  const options = mapping?.mapping?.options;

  // Preserve the card-level origin through edits (per-row badges still flip to
  // Manual) so a later Regenerate can honour it.
  const commit = (nextDisplay) =>
    onChange({
      display: nextDisplay,
      mapping: rebuildMapping(nextDisplay, options),
      origin: mapping?.origin,
    });

  // Editing a row's source/target/role flips a generated row to "user-edited"
  // so a later Regenerate preserves it; a "user-added" row keeps its origin.
  const updateRow = (index, patch) => {
    const nextDisplay = display.map((row, i) => {
      if (i !== index) return row;
      const provenance = row.provenance === "user-added" ? "user-added" : "user-edited";
      return { ...row, ...patch, provenance };
    });
    commit(nextDisplay);
  };

  // A blank row the user fills in from the dropdowns (source + target + role).
  // Tagged "user-added" so it survives Regenerate and wins over any generated
  // pairing for the same source column.
  const addRow = () => {
    commit([
      ...display,
      { logical: "", source_col: "", target_col: "", role: KEY_ROLE, reason: "", provenance: "user-added" },
    ]);
  };

  const removeRow = (index) => commit(display.filter((_, i) => i !== index));

  return (
    <div className="mapping-editor">
      <div className="mapping-editor__head">
        <div>
          <p className="wizard-field__help">
            Confirm the source-to-target field mapping. Adjust the target column or role for any row,
            or add a row for a missing pairing.
          </p>
        </div>
        <div className="mapping-editor__head-actions">
          <Button type="button" variant="ghost" onClick={addRow} disabled={loading}>
            + Add mapping row
          </Button>
          <Button type="button" variant="outline" onClick={onRegenerate} disabled={loading}>
            {loading ? "Mapping…" : "Regenerate mapping"}
          </Button>
        </div>
      </div>

      {error && <p className="wizard-step__error">{error}</p>}
      {notice && !error && <p className="wizard-step__hint">{notice}</p>}
      {loading && !display.length && <p className="wizard-step__hint">Inferring column mapping…</p>}
      {!loading && !display.length && !error && (
        <p className="wizard-field__help">
          No field mapping could be generated. Regenerate once the data is available, or use “Add
          mapping row” to build the field mapping manually.
        </p>
      )}

      {display.length > 0 && (
        <div className="surface-elevated mapping-editor__table-wrap">
          <table className="table-elevated mapping-editor__table">
            <thead>
              <tr>
                <th>Logical Field</th>
                <th>Source Field</th>
                <th>Target Field</th>
                <th>Mapping Type</th>
                <th>Origin</th>
                <th aria-label="Row actions"></th>
              </tr>
            </thead>
            <tbody>
              {display.map((row, index) => {
                const origin = ORIGIN_BADGE[row.provenance] ?? ORIGIN_BADGE.generated;
                return (
                  <tr key={`${row.source_col || "new"}-${index}`}>
                    <td className="mapping-editor__logical">{row.logical}</td>
                    <td>
                      {row.provenance === "user-added" ? (
                        <Select
                          className="h-8 text-xs"
                          value={row.source_col ?? ""}
                          onChange={(e) => updateRow(index, { source_col: e.target.value })}
                          options={[
                            { value: "", label: "— select source —" },
                            ...sourceColumns.map((col) => ({ value: col, label: col })),
                          ]}
                        />
                      ) : (
                        row.source_col
                      )}
                    </td>
                    <td>
                      <Select
                        className="h-8 text-xs"
                        value={row.target_col ?? ""}
                        onChange={(e) => updateRow(index, { target_col: e.target.value })}
                        options={[
                          { value: "", label: "— none —" },
                          ...targetColumns.map((col) => ({ value: col, label: col })),
                        ]}
                      />
                    </td>
                    <td>
                      <Select
                        className="h-8 text-xs"
                        value={isKeyRole(row.role) ? "key" : "compare"}
                        onChange={(e) =>
                          updateRow(index, { role: e.target.value === "key" ? KEY_ROLE : COMPARE_ROLE })
                        }
                        options={[
                          { value: "key", label: "🔑 Key" },
                          { value: "compare", label: "📊 Compare" },
                        ]}
                      />
                    </td>
                    <td>
                      <Badge variant={origin.variant}>{origin.label}</Badge>
                    </td>
                    <td>
                      {isUserRow(row) && (
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-8 text-xs"
                          onClick={() => removeRow(index)}
                          aria-label="Remove row"
                        >
                          Remove
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default MappingEditor;
