// Aggregation Rules builder — aggregate/group source data before reconciliation.
// Each row is { field, aggregation } and compiles to the contract's
// aggregation_rules, applied deterministically in the shadow Aggregation stage.

import { Button, Select, EmptyState } from "@bristlecone/canopy";

const AGGREGATION_OPTIONS = [
  { value: "sum", label: "Sum" },
  { value: "count", label: "Count" },
  { value: "average", label: "Average" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
  { value: "group_by_day", label: "Group By Date (Day)" },
  { value: "group_by_week", label: "Group By Week" },
  { value: "group_by_month", label: "Group By Month" },
  { value: "group_by_quarter", label: "Group By Quarter" },
  { value: "group_by_year", label: "Group By Year" },
];

function AggregationRow({ rule, fieldOptions, onChange, onRemove }) {
  const touched = Boolean(rule.field) || Boolean(rule.aggregation);
  return (
    <tr>
      <td>
        <Select
          className="h-8 text-xs"
          value={rule.field}
          onChange={(e) => onChange({ ...rule, field: e.target.value })}
          options={[{ value: "", label: "— select source field —" }, ...fieldOptions]}
        />
        {touched && !rule.field && <p className="wizard-step__error">Field is required.</p>}
      </td>
      <td>
        <Select
          className="h-8 text-xs"
          value={rule.aggregation}
          onChange={(e) => onChange({ ...rule, aggregation: e.target.value })}
          options={[{ value: "", label: "— select aggregation —" }, ...AGGREGATION_OPTIONS]}
        />
        {touched && !rule.aggregation && <p className="wizard-step__error">Aggregation is required.</p>}
      </td>
      <td>
        <Button type="button" variant="outline" size="sm" onClick={onRemove}>
          − Remove
        </Button>
      </td>
    </tr>
  );
}

function AggregationRulesBuilder({ fieldOptions, rules, onChange }) {
  const updateRow = (index, next) => onChange(rules.map((r, i) => (i === index ? next : r)));
  const removeRow = (index) => onChange(rules.filter((_, i) => i !== index));
  const addRow = () => onChange([...rules, { field: "", aggregation: "" }]);

  return (
    <div className="rule-builder__section">
      <div className="mapping-editor__head">
        <div>
          <p className="wizard-field__help">
            Aggregate source data before reconciliation. Measures (Sum/Count/Average/Min/Max) are
            aggregated within each business-key group; "Group By" buckets a date field to a coarser
            period so it becomes a grouping dimension.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={addRow}>
          + Add Aggregation Rule
        </Button>
      </div>

      {rules.length > 0 ? (
        <div className="surface-elevated mapping-editor__table-wrap">
          <table className="table-elevated mapping-editor__table">
            <thead>
              <tr>
                <th>Source Field</th>
                <th>Aggregation</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule, index) => (
                <AggregationRow
                  key={index}
                  rule={rule}
                  fieldOptions={fieldOptions}
                  onChange={(next) => updateRow(index, next)}
                  onRemove={() => removeRow(index)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No aggregation rules defined yet." />
      )}
    </div>
  );
}

export default AggregationRulesBuilder;
