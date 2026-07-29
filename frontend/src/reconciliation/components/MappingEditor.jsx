import { isKeyRole, isUserRow, rebuildMapping } from "../lib/payload";
import { FIELD_ROLES, fieldRoleLabel, detectFieldRole } from "../lib/fieldRoleAliases";
import { Button, Select, Badge, Alert, Skeleton, EmptyState } from "@bristlecone/canopy";

const KEY_ROLE = "🔑 Key";
const COMPARE_ROLE = "📊 Compare";

// "Business Field" dropdown options — the canonical role Deterministic
// Mapping resolves by (see resolveValueMappingFields), not the row's literal
// column names. "— none —" means this pairing doesn't feed Deterministic
// Mapping (still fine for Manual Mapping's contract).
const BUSINESS_FIELD_OPTIONS = [
  { value: "", label: "— none —" },
  ...Object.values(FIELD_ROLES).map((role) => ({ value: role, label: fieldRoleLabel(role) })),
];

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
  // Renaming the source or target column re-detects the Business Field from
  // the new name (e.g. fixing a typo'd header) UNLESS the edit itself already
  // sets field_role explicitly (the Business Field dropdown) — that always
  // wins, and a rename that matches no alias keeps whatever tag was there.
  const updateRow = (index, patch) => {
    const nextDisplay = display.map((row, i) => {
      if (i !== index) return row;
      const provenance = row.provenance === "user-added" ? "user-added" : "user-edited";
      const next = { ...row, ...patch, provenance };
      if (patch.field_role === undefined && ("source_col" in patch || "target_col" in patch)) {
        next.field_role = detectFieldRole(next.source_col, next.target_col) ?? next.field_role ?? null;
      }
      return next;
    });
    commit(nextDisplay);
  };

  // A blank row the user fills in from the dropdowns (source + target + role).
  // Tagged "user-added" so it survives Regenerate and wins over any generated
  // pairing for the same source column.
  const addRow = () => {
    commit([
      ...display,
      {
        logical: "",
        source_col: "",
        target_col: "",
        role: KEY_ROLE,
        reason: "",
        provenance: "user-added",
        field_role: null,
      },
    ]);
  };

  const removeRow = (index) => commit(display.filter((_, i) => i !== index));

  return (
    <div className="mapping-editor">
      <div className="mapping-editor__head">
        <div>
          <p className="wizard-field__help">
            Confirm the source-to-target field mapping. Adjust the target column or role for any row,
            or add a row for a missing pairing. "Business Field" is auto-detected from the column names
            for Deterministic Mapping — retag it if a required field wasn't recognized.
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

      {error && <Alert variant="error" style={{ marginTop: 8 }}>{error}</Alert>}
      {notice && !error && <Alert variant="info" style={{ marginTop: 8 }}>{notice}</Alert>}
      {loading && !display.length && (
        <div style={{ display: "grid", gap: 8, marginTop: 8 }} aria-label="Inferring column mapping…">
          <Skeleton style={{ height: 32 }} />
          <Skeleton style={{ height: 32 }} />
          <Skeleton style={{ height: 32 }} />
        </div>
      )}
      {!loading && !display.length && !error && (
        <EmptyState
          title="No field mapping yet"
          description="No field mapping could be generated. Regenerate once the data is available, or use “Add mapping row” to build the field mapping manually."
        />
      )}

      {display.length > 0 && (
        <div className="surface-elevated mapping-editor__table-wrap">
          <table className="table-elevated mapping-editor__table">
            <thead>
              <tr>
                <th>Source Field</th>
                <th>Target Field</th>
                <th>Mapping Type</th>
                <th>Business Field</th>
                <th>Origin</th>
                <th aria-label="Row actions"></th>
              </tr>
            </thead>
            <tbody>
              {display.map((row, index) => {
                const origin = ORIGIN_BADGE[row.provenance] ?? ORIGIN_BADGE.generated;
                return (
                  <tr key={`${row.source_col || "new"}-${index}`}>
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
                      <Select
                        className="h-8 text-xs"
                        value={row.field_role ?? ""}
                        onChange={(e) => updateRow(index, { field_role: e.target.value || null })}
                        options={BUSINESS_FIELD_OPTIONS}
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
