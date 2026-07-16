// Client-side CSV export for datasets already held in memory (no re-fetch
// from the source system). Used by the SAP S/4 and IBP dataset workspaces'
// "Download Data" action.

function csvCell(value) {
  if (value === null || value === undefined) return "";
  const str = typeof value === "string" ? value : String(value);
  return /[",\n\r]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

export function rowsToCsv(columns, rows) {
  const header = columns.map(csvCell).join(",");
  const lines = rows.map((row) => columns.map((c) => csvCell(row[c])).join(","));
  return [header, ...lines].join("\r\n");
}

export function buildExportFilename(sourceSystem, datasetName, date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  const timestamp =
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  const safeName = (datasetName || "dataset").replace(/[^A-Za-z0-9_-]/g, "_");
  return `${sourceSystem}_${safeName}_${timestamp}.csv`;
}

function triggerCsvDownload(filename, csvString) {
  // BOM so Excel opens non-ASCII values (e.g. SAP text fields) correctly.
  const blob = new Blob(["﻿" + csvString], { type: "text/csv;charset=utf-8;" });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

// Exports the full dataset (not a preview subset) exactly as received from
// the source system. Yields to the event loop first so a "Preparing…" state
// can paint before the CSV build blocks the main thread on large datasets.
export async function exportDatasetToCsv({ sourceSystem, datasetName, columns, rows }) {
  if (!columns?.length) throw new Error("No columns available to export");
  if (!rows?.length) throw new Error("No rows available to export");
  await new Promise((resolve) => setTimeout(resolve, 0));
  const csv = rowsToCsv(columns, rows);
  const filename = buildExportFilename(sourceSystem, datasetName);
  triggerCsvDownload(filename, csv);
}
