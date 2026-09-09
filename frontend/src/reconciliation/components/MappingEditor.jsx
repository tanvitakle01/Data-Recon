import { isKeyRole, isUserRow, rebuildMapping } from "../lib/payload";
import { FIELD_ROLES, fieldRoleLabel, detectFieldRole } from "../lib/fieldRoleAliases";
import { Button, Select, Badge, Alert, Skeleton, EmptyState } from "@bristlecone/canopy";

const KEY_ROLE = "🔑 Key";
const COMPARE_ROLE = "📊 Compare";

// "Business Field" dropdown options — an optional semantic tag shown in the
// UI and used to spot the date pair (see field_role usage in payload.js);
// Deterministic Mapping itself pairs every confirmed Key row regardless of
// whether it has a tag. "— none —" means no semantic role, still fine for
// both Deterministic and Manual Mapping.
const BUSINESS_FIELD_OPTIONS = [
  { value: "", label: "— none —" },
  ...Object.values(FIELD_ROLES).map((role) => ({ value: role, label: fieldRoleLabel(role) })),
];

// Per-row origin badge (the "Origin" column). Library/Azure AI Foundry are
// the generated tiers; user-added/user-edited are the manual tier.
// gemini/groq/openai are kept for old rows generated before the LLM layer
// became Azure-AI-Foundry-only.
const ORIGIN_BADGE = {
  library: { label: "Vector Library", variant: "info" },
  azure_foundry: { label: "Azure AI Foundry", variant: "default" },
  gemini: { label: "Gemini", variant: "default" },
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
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">Field mapping</h3>
        <span className="ct-card__spacer" />
        <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={loading}>
          + Add row
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={onRegenerate} disabled={loading}>
          {loading ? "Mapping…" : "Regenerate"}
        </Button>
      </div>

      <div className="ct-card__body">
        {error && <Alert variant="error">{error}</Alert>}
        {notice && !error && <Alert variant="info">{notice}</Alert>}
        {loading && !display.length && (
          <div style={{ display: "grid", gap: 8 }} aria-label="Inferring column mapping…">
            <Skeleton style={{ height: 32 }} />
            <Skeleton style={{ height: 32 }} />
            <Skeleton style={{ height: 32 }} />
          </div>
        )}
        {!loading && !display.length && !error && (
          <EmptyState
            title="No field mapping yet"
            description="No field mapping could be generated. Regenerate once the data is available, or use “Add row” to build the field mapping manually."
          />
        )}
      </div>

      {display.length > 0 && (
        <div className="ct-table-wrap">
          <table className="ct-table">
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
    </section>
  );
}

export default MappingEditor;
