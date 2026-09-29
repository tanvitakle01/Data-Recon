import api from "../../services/api";

// Client side of the multi-file source upload: file bookkeeping, join-step
// defaults and the calls to /api/files/join. The join itself is deterministic
// parsing on the backend (backend/excel_comparator/core/multi_file_join.py) —
// no AI, no fuzzy matching; every key pair is either an exact shared column
// name or one the user picked explicitly.

export const MAX_JOIN_FILES = 5;
export const PREVIEW_ROWS = 10;

export const JOIN_TYPE_OPTIONS = [
  { value: "left", label: "Left — keep every row of the files above" },
  { value: "inner", label: "Inner — only rows matched in both" },
  { value: "outer", label: "Outer — every row from both sides" },
];

let nextId = 1;
export function newEntryId() {
  nextId += 1;
  return `mf-${Date.now()}-${nextId}`;
}

// "excel" | "csv" | null — .xlsx and .xls count as the same family.
export function fileFamily(filename) {
  const name = (filename || "").toLowerCase();
  if (name.endsWith(".csv")) return "csv";
  if (name.endsWith(".xlsx") || name.endsWith(".xls")) return "excel";
  return null;
}

export async function fetchFilePreview(file, sheetName = null) {
  const formData = new FormData();
  formData.append("file", file);
  if (sheetName) formData.append("sheet_name", sheetName);
  const res = await api.post("/preview", formData);
  return res.data;
}

// One uploaded file as the panel tracks it, built from a /preview response.
export function toEntry(file, data, id = newEntryId()) {
  return {
    id,
    file,
    filename: data?.filename ?? file?.name ?? "",
    family: fileFamily(data?.filename ?? file?.name),
    sheet: data?.active_sheet ?? null,
    sheets: data?.sheets ?? [],
    columns: data?.columns ?? [],
    rows: data?.rows ?? 0,
    cols: data?.cols ?? 0,
    preview: data?.preview ?? [],
  };
}

// Column names of `files[index]` that also appear in any earlier file, in the
// right-hand file's own column order.
export function commonColumns(files, index) {
  const prior = new Set(files.slice(0, index).flatMap((f) => f.columns));
  return files[index].columns.filter((c) => prior.has(c));
}

// Starting configuration for joining files[index] onto files[0..index-1].
// Exactly one shared column name → auto-joined on it. Several → the user picks
// which one. None → manual pairing of a column from each side.
export function defaultStep(files, index) {
  const common = commonColumns(files, index);
  return {
    mode: common.length > 0 ? "common" : "manual",
    commonColumn: common.length === 1 ? common[0] : "",
    auto: common.length === 1,
    leftId: files[0]?.id ?? "",
    leftColumn: "",
    rightColumn: "",
    how: "left",
  };
}

// {left_file, left_column, right_column, how} for the backend, or null while
// the step is incomplete or refers to a column that no longer exists.
export function resolveStep(step, files, index) {
  if (!step) return null;
  const right = files[index];
  if (step.mode === "common") {
    if (!step.commonColumn || !right.columns.includes(step.commonColumn)) return null;
    const leftFile = files.slice(0, index).findIndex((f) => f.columns.includes(step.commonColumn));
    if (leftFile < 0) return null;
    return { left_file: leftFile, left_column: step.commonColumn, right_column: step.commonColumn, how: step.how };
  }
  const leftFile = files.slice(0, index).findIndex((f) => f.id === step.leftId);
  if (leftFile < 0 || !files[leftFile].columns.includes(step.leftColumn)) return null;
  if (!right.columns.includes(step.rightColumn)) return null;
  return { left_file: leftFile, left_column: step.leftColumn, right_column: step.rightColumn, how: step.how };
}

// Full backend config, or null if any step is incomplete.
export function buildJoinConfig(files, stepsById, sort) {
  if (files.length < 2) return null;
  const steps = [];
  for (let i = 1; i < files.length; i += 1) {
    const resolved = resolveStep(stepsById[files[i].id], files, i);
    if (!resolved) return null;
    steps.push(resolved);
  }
  const sortStep = sort ? files.findIndex((f) => f.id === sort.rightId) - 1 : -1;
  return {
    sheets: files.map((f) => f.sheet ?? null),
    steps,
    sort: sortStep >= 0 ? { step: sortStep, direction: sort.direction } : null,
  };
}

// Identity of a join: which files (by entry id), which sheets, which config.
// A committed combined dataset is current only while this is unchanged.
export function joinSignature(files, config) {
  return JSON.stringify({ ids: files.map((f) => f.id), config });
}

async function blobErrorDetail(err) {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      return JSON.parse(await data.text())?.detail;
    } catch {
      return null;
    }
  }
  return data?.detail;
}

export async function requestJoin(files, config, mode = "preview") {
  const formData = new FormData();
  for (const entry of files) formData.append("files", entry.file, entry.filename);
  formData.append("config", JSON.stringify(config));
  formData.append("mode", mode);
  formData.append("preview_rows", String(PREVIEW_ROWS));
  try {
    const res = await api.post("/api/files/join", formData, mode === "build" ? { responseType: "blob" } : undefined);
    return res.data;
  } catch (err) {
    const detail = await blobErrorDetail(err);
    throw new Error(detail || err?.message || "Join failed", { cause: err });
  }
}
