// Structured Business Rules Builder — replaces the free-text
// "Additional Rules / Instructions" textarea. Produces three ordered arrays
// of { field, instruction } rows (transformation / matching / filter), kept
// in wizard state and sent to the backend as machine-readable JSON instead
// of a single unstructured string.
//
// Categories are intentionally just three <RuleSection> instances rendered
// side by side here — adding a future category is a matter of adding one
// more <RuleSection>, so the set stays easy to extend without touching the
// shared row/table rendering below.

import { Button, Select } from "@bristlecone/canopy";

function RuleRow({ rule, fieldOptions, onChange, onRemove, removeLabel }) {
  const touched = Boolean(rule.field) || Boolean(rule.instruction);
  const fieldMissing = touched && !rule.field;
  const instructionMissing = touched && !rule.instruction;

  return (
    <tr>
      <td>
        <Select
          className="h-8 text-xs"
          value={rule.field}
          onChange={(e) => onChange({ ...rule, field: e.target.value })}
          options={[{ value: "", label: "— select field —" }, ...fieldOptions]}
        />
        {fieldMissing && <p className="wizard-step__error">Field is required.</p>}
      </td>
      <td>
        <input
          type="text"
          className="wizard-input wizard-input--sm"
          placeholder="e.g. Remove leading zeros"
          value={rule.instruction}
          onChange={(e) => onChange({ ...rule, instruction: e.target.value })}
        />
        {instructionMissing && <p className="wizard-step__error">Instruction is required.</p>}
      </td>
      <td>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRemove}
        >
          − {removeLabel}
        </Button>
      </td>
    </tr>
  );
}

function RuleSection({
  title,
  help,
  addLabel,
  removeLabel,
  fieldColumnLabel,
  instructionColumnLabel,
  fieldOptions,
  rules,
  onChange,
}) {
  const updateRow = (index, nextRow) => {
    onChange(rules.map((r, i) => (i === index ? nextRow : r)));
  };
  const removeRow = (index) => onChange(rules.filter((_, i) => i !== index));
  const addRow = () => onChange([...rules, { field: "", instruction: "" }]);

  return (
    <div className="rule-builder__section">
      <div className="mapping-editor__head">
        <div>
          <h4 className="rule-builder__section-title">{title}</h4>
          <p className="wizard-field__help">{help}</p>
        </div>
        <Button type="button" variant="outline" onClick={addRow}>
          + {addLabel}
        </Button>
      </div>

      {rules.length > 0 ? (
        <div className="surface-elevated mapping-editor__table-wrap">
          <table className="table-elevated mapping-editor__table">
            <thead>
              <tr>
                <th>{fieldColumnLabel}</th>
                <th>{instructionColumnLabel}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule, index) => (
                <RuleRow
                  key={index}
                  rule={rule}
                  fieldOptions={fieldOptions}
                  removeLabel={removeLabel}
                  onChange={(nextRow) => updateRow(index, nextRow)}
                  onRemove={() => removeRow(index)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="wizard-step__hint">No {title.toLowerCase()} defined yet.</p>
      )}
    </div>
  );
}

function BusinessRulesBuilder({
  fieldOptions,
  transformationRules,
  matchingRules,
  filterRules,
  onChangeCategory,
}) {
  return (
    <div className="rule-builder">
      <RuleSection
        title="Transformations"
        help="Modify source values before reconciliation."
        addLabel="Add Transformation Rule"
        removeLabel="Remove"
        fieldColumnLabel="Source Field"
        instructionColumnLabel="Instruction"
        fieldOptions={fieldOptions}
        rules={transformationRules}
        onChange={(rules) => onChangeCategory("transformationRules", rules)}
      />
      <RuleSection
        title="Matching"
        help="Define equivalence rules."
        addLabel="Add Matching Rule"
        removeLabel="Remove"
        fieldColumnLabel="Field"
        instructionColumnLabel="Rule"
        fieldOptions={fieldOptions}
        rules={matchingRules}
        onChange={(rules) => onChangeCategory("matchingRules", rules)}
      />
      <RuleSection
        title="Filters"
        help="Include or exclude source records."
        addLabel="Add Filter Rule"
        removeLabel="Remove"
        fieldColumnLabel="Field"
        instructionColumnLabel="Rule"
        fieldOptions={fieldOptions}
        rules={filterRules}
        onChange={(rules) => onChangeCategory("filterRules", rules)}
      />
    </div>
  );
}

export default BusinessRulesBuilder;
