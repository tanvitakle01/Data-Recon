import { useMemo, useState } from "react";

const STATUS_TONE = {
  Match: "match",
  "Quantity Mismatch": "qty",
  "Missing in Target": "missing",
  "Extra in Target": "extra",
  Paired: "match",
  Unpaired: "missing",
};

function toneFor(value) {
  return STATUS_TONE[value] || "neutral";
}

// Generic drill-through table: renders whatever columns `/insights/records`
// returns (All Records-shaped rows, or Mapping Details rows when the filter
// is a mappingUnpaired drill) — column sort + CSV export, no click-to-expand.
export default function RecordsTable({ title, columns, rows, totalMatched, onClear, onExport, busy }) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("asc");

  const visibleColumns = useMemo(() => columns.filter((c) => c !== "__status__"), [columns]);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv), undefined, { numeric: true });
    });
    if (sortDir === "desc") copy.reverse();
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggleSort = (col) => {
    if (sortKey !== col) {
      setSortKey(col);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortKey(null);
      setSortDir("asc");
    }
  };

  return (
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">{title}</h3>
        <span className="ct-card__spacer" />
        <span style={{ color: "var(--muted)", fontSize: 12.5, fontWeight: 600, marginRight: 10 }}>
          {totalMatched} record{totalMatched === 1 ? "" : "s"}
        </span>
        <button type="button" className="btn-secondary" onClick={onExport} disabled={busy || !rows.length}>
          Export CSV
        </button>
        <button type="button" className="btn-secondary" onClick={onClear} style={{ marginLeft: 8 }}>
          Clear filter
        </button>
      </div>
      <div className="ct-card__body ct-card__body--flush">
        {!rows.length && (
          <div style={{ padding: 14 }}>
            <p className="wizard-field__help" style={{ margin: 0 }}>
              No records match this filter.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  {visibleColumns.map((c) => (
                    <th key={c} onClick={() => toggleSort(c)} style={{ cursor: "pointer", userSelect: "none" }}>
                      {c}
                      {sortKey === c ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((rec, i) => (
                  <tr key={i}>
                    {visibleColumns.map((c) =>
                      c === "Status" || c === "Status Detail" ? (
                        <td key={c}>
                          <span className={`status-badge status-badge--${toneFor(rec[c])}`}>
                            <span className="status-badge__dot" />
                            {rec[c]}
                          </span>
                        </td>
                      ) : (
                        <td key={c}>{rec[c] === null || rec[c] === undefined ? "—" : String(rec[c])}</td>
                      )
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {totalMatched > rows.length && (
          <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border)" }}>
            <span className="wizard-field__help" style={{ margin: 0 }}>
              Showing {rows.length} of {totalMatched} — export CSV for the full set.
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
