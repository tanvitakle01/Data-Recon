import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Select } from "@bristlecone/canopy";
import { FileSpreadsheet, Plus, RefreshCw, X } from "lucide-react";
import FileUploadCard from "../../components/FileUploadCard";
import DatasetPreviewCard from "./DatasetPreviewCard";
import Chevron from "./Chevron";
import {
  JOIN_TYPE_OPTIONS,
  MAX_JOIN_FILES,
  buildJoinConfig,
  commonColumns,
  defaultStep,
  fetchFilePreview,
  fileFamily,
  joinSignature,
  requestJoin,
  toEntry,
} from "../lib/multiFileJoin";

// Source slot that accepts up to MAX_JOIN_FILES files and joins them into one
// combined dataset. One file behaves exactly like the single-file upload (same
// Dataset Preview card, plus an "Add file" button). From two files on, the
// panel shows the file list, the join settings, the join diagnostics and a
// combined preview; nothing reaches wizard state until the user applies the
// combined result, which then travels downstream as an ordinary uploaded file.
const ACCEPT = ".xlsx,.xls,.csv";
const FAMILY_LABEL = { excel: "Excel", csv: "CSV" };

function initialState(dataset) {
  if (dataset?.multiFile) {
    const { files, stepsById, sort, signature } = dataset.multiFile;
    return { files, stepsById, sort, appliedSig: signature };
  }
  if (dataset?.file) {
    const entry = toEntry(dataset.file, {
      filename: dataset.filename,
      active_sheet: dataset.sheet,
      sheets: dataset.sheets,
      columns: dataset.columns,
      rows: dataset.rowCount,
      cols: dataset.colCount,
      preview: dataset.preview,
    });
    return { files: [entry], stepsById: {}, sort: null, appliedSig: null };
  }
  return { files: [], stepsById: {}, sort: null, appliedSig: null };
}

// A join result the user must look at: rows multiplied by duplicate keys, or
// a key pair that matched nothing.
function hasWarnings(data) {
  return Boolean(data?.steps?.some((s) => s.extra_rows_from_duplicates > 0 || s.matched_left_rows === 0));
}

function PreviewTable({ columns, rows }) {
  return (
    <div className="ct-table-wrap">
      <table className="ct-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((col) => (
                <td key={col} className="mono">
                  {row[col]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MultiFileSourcePanel({ role, dataset, onDatasetReady, onCleared, onPendingChange }) {
  const [init] = useState(() => initialState(dataset));
  const [files, setFiles] = useState(init.files);
  const [stepsById, setStepsById] = useState(init.stepsById);
  const [sort, setSort] = useState(init.sort);
  const [appliedSig, setAppliedSig] = useState(init.appliedSig);
  const [fileError, setFileError] = useState(null);
  const [busyFileId, setBusyFileId] = useState(null);
  const [adding, setAdding] = useState(false);
  const [showUploadAgain, setShowUploadAgain] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(() => {
    const steps = Object.values(init.stepsById);
    return !(steps.length > 0 && steps.every((s) => s.auto));
  });
  const [preview, setPreview] = useState({ loading: false, data: null, error: null, sig: null });
  const [ackSig, setAckSig] = useState(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState(null);

  const addInputRef = useRef(null);
  const replaceInputRef = useRef(null);
  const replaceTargetRef = useRef(null);
  const requestSeq = useRef(0);
  // File reads are async: handlers that await one must apply their result to
  // whatever the files/steps are *now*, not the values they captured before
  // the await (the user may have removed a file or edited a join meanwhile).
  const latest = useRef({ files, stepsById, dataset });
  useEffect(() => {
    latest.current = { files, stepsById, dataset };
  });

  const isMulti = files.length >= 2;
  const config = useMemo(() => buildJoinConfig(files, stepsById, sort), [files, stepsById, sort]);
  const signature = config ? joinSignature(files, config) : null;
  const pending = isMulti && (!signature || signature !== appliedSig);

  useEffect(() => {
    onPendingChange?.(pending);
  }, [pending, onPendingChange]);

  // ── single-file application (unchanged downstream shape) ──────────────
  const applySingle = (entry) => {
    const { dataset } = latest.current;
    const unchanged =
      dataset && !dataset.multiFile && dataset.file === entry.file && (dataset.sheet ?? null) === (entry.sheet ?? null);
    if (unchanged) return;
    onDatasetReady(
      { filename: entry.filename, columns: entry.columns, preview: entry.preview, rows: entry.rows, cols: entry.cols },
      entry.file,
      { sheet_name: entry.sheet, sheets: entry.sheets },
    );
  };

  // Files changed → any step that pointed at a removed/changed file, or whose
  // right-hand file is new, falls back to its default. Everything else keeps
  // the user's choices.
  const reconcileSteps = (nextFiles, touchedIds = new Set()) => {
    const next = {};
    let defaulted = false;
    nextFiles.forEach((entry, index) => {
      if (index === 0) return;
      const existing = latest.current.stepsById[entry.id];
      const leftGone =
        existing?.mode === "manual" &&
        (touchedIds.has(existing.leftId) || !nextFiles.slice(0, index).some((f) => f.id === existing.leftId));
      if (existing && !touchedIds.has(entry.id) && !leftGone) {
        next[entry.id] = existing;
      } else {
        next[entry.id] = defaultStep(nextFiles, index);
        defaulted = true;
      }
    });
    latest.current.stepsById = next;
    setStepsById(next);
    // Auto-joined (single shared column) steps need no input, so the settings
    // start collapsed; anything the user has to choose opens them.
    if (defaulted) setSettingsOpen(!Object.values(next).every((s) => s.auto));
    setSort((prev) => (prev && nextFiles.some((f, i) => i > 0 && f.id === prev.rightId) ? prev : null));
  };

  const commitFiles = (nextFiles, touchedIds) => {
    latest.current.files = nextFiles;
    setFiles(nextFiles);
    reconcileSteps(nextFiles, touchedIds);
    setApplyError(null);
    if (nextFiles.length === 1) applySingle(nextFiles[0]);
    if (nextFiles.length === 0) onCleared();
  };

  const checkFamily = (file, others) => {
    const family = fileFamily(file?.name);
    if (!family) return "Unsupported file type. Upload .xlsx, .xls or .csv.";
    const expected = others[0]?.family;
    if (expected && family !== expected) {
      return `All files in one slot must be the same type — this slot holds ${FAMILY_LABEL[expected]} files, "${file.name}" is ${FAMILY_LABEL[family]}.`;
    }
    return null;
  };

  // ── add / replace / remove / sheet ─────────────────────────────────────
  const handleAdd = async (file) => {
    if (!file) return;
    setFileError(null);
    if (files.length >= MAX_JOIN_FILES) {
      setFileError(`At most ${MAX_JOIN_FILES} files can be joined into one source.`);
      return;
    }
    const familyError = checkFamily(file, files);
    if (familyError) {
      setFileError(familyError);
      return;
    }
    setAdding(true);
    try {
      const data = await fetchFilePreview(file);
      const current = latest.current.files;
      const lateError =
        current.length >= MAX_JOIN_FILES
          ? `At most ${MAX_JOIN_FILES} files can be joined into one source.`
          : checkFamily(file, current);
      if (lateError) setFileError(lateError);
      else commitFiles([...current, toEntry(file, data)]);
    } catch (e) {
      setFileError(e?.response?.data?.detail || `Could not read "${file.name}".`);
    } finally {
      setAdding(false);
    }
  };

  const handleReplace = async (id, file) => {
    if (!file) return;
    setFileError(null);
    const others = files.filter((f) => f.id !== id);
    const familyError = checkFamily(file, others);
    if (familyError) {
      setFileError(familyError);
      return;
    }
    setBusyFileId(id);
    try {
      const data = await fetchFilePreview(file);
      const replacement = toEntry(file, data);
      const current = latest.current.files;
      if (!current.some((f) => f.id === id)) return; // removed while reading
      commitFiles(
        current.map((f) => (f.id === id ? replacement : f)),
        new Set([id, replacement.id]),
      );
    } catch (e) {
      setFileError(e?.response?.data?.detail || `Could not read "${file.name}".`);
    } finally {
      setBusyFileId(null);
    }
  };

  const handleRemove = (id) => {
    setFileError(null);
    commitFiles(files.filter((f) => f.id !== id), new Set([id]));
  };

  const handleSheetChange = async (id, sheet) => {
    const entry = files.find((f) => f.id === id);
    if (!entry) return;
    setBusyFileId(id);
    setFileError(null);
    try {
      const data = await fetchFilePreview(entry.file, sheet);
      const updated = toEntry(entry.file, data, entry.id);
      const current = latest.current.files;
      if (!current.some((f) => f.id === id)) return; // removed while reading
      commitFiles(
        current.map((f) => (f.id === id ? updated : f)),
        new Set([id]),
      );
    } catch (e) {
      setFileError(e?.response?.data?.detail || "Sheet preview failed");
    } finally {
      setBusyFileId(null);
    }
  };

  // First file via the standard upload card (also handles its sheet picker).
  const handleFirstLoaded = (data, file) => {
    if (!data) {
      commitFiles([]);
      return;
    }
    setShowUploadAgain(false);
    const entry = toEntry(file, data, files.length === 1 && files[0].file === file ? files[0].id : undefined);
    commitFiles([entry], new Set([entry.id]));
  };

  const updateStep = (id, patch) => setStepsById((prev) => ({ ...prev, [id]: { ...prev[id], ...patch, auto: false } }));

  const toggleSort = (rightId, direction) =>
    setSort((prev) => (prev?.rightId === rightId && prev.direction === direction ? null : { rightId, direction }));

  // ── live join preview (debounced) ──────────────────────────────────────
  useEffect(() => {
    if (!isMulti || !config) return undefined;
    const seq = ++requestSeq.current;
    const sig = signature;
    const timer = setTimeout(async () => {
      setPreview((p) => ({ ...p, loading: true, error: null }));
      try {
        const data = await requestJoin(files, config, "preview");
        if (seq !== requestSeq.current) return;
        setPreview({ loading: false, data, error: null, sig });
        // The result lives in the collapsible card: never keep a warning hidden.
        if (hasWarnings(data)) setSettingsOpen(true);
      } catch (e) {
        if (seq === requestSeq.current) setPreview({ loading: false, data: null, error: e.message, sig });
      }
    }, 350);
    return () => clearTimeout(timer);
    // signature captures every input that changes the join.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, isMulti]);

  const current = preview.sig === signature ? preview.data : null;
  const extraRows = current?.steps?.reduce((n, s) => n + s.extra_rows_from_duplicates, 0) ?? 0;
  const needsAck = extraRows > 0 && ackSig !== signature;
  const needsReview = needsAck || Boolean(current?.steps?.some((s) => s.matched_left_rows === 0));
  const isApplied = isMulti && signature && signature === appliedSig;

  const handleApply = async () => {
    if (!current || !config) return;
    setApplying(true);
    setApplyError(null);
    try {
      const blob = await requestJoin(files, config, "build");
      const family = files[0].family;
      const combinedFile = new File([blob], current.filename, {
        type:
          family === "csv"
            ? "text/csv"
            : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      onDatasetReady(
        {
          filename: current.filename,
          columns: current.columns,
          preview: current.preview,
          rows: current.rows,
          cols: current.cols,
        },
        combinedFile,
        { sheet_name: family === "csv" ? null : "Combined", sheets: family === "csv" ? [] : ["Combined"] },
        {
          multiFile: {
            files,
            stepsById,
            sort,
            signature,
            sourceFiles: files.map((f) => ({ filename: f.filename, sheet: f.sheet, rows: f.rows, cols: f.cols })),
            summary: current,
          },
        },
      );
      setAppliedSig(signature);
    } catch (e) {
      setApplyError(e.message);
    } finally {
      setApplying(false);
    }
  };

  const hiddenInputs = (
    <>
      <input
        ref={addInputRef}
        type="file"
        accept={ACCEPT}
        style={{ display: "none" }}
        onChange={(e) => {
          handleAdd(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
      <input
        ref={replaceInputRef}
        type="file"
        accept={ACCEPT}
        style={{ display: "none" }}
        onChange={(e) => {
          handleReplace(replaceTargetRef.current, e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
    </>
  );

  const openAdd = () => addInputRef.current?.click();
  const atCap = files.length >= MAX_JOIN_FILES;

  // ── 0 files / replacing the only file ─────────────────────────────────
  if (files.length === 0 || (files.length === 1 && showUploadAgain)) {
    return (
      <div className="wizard-connector-panel">
        <FileUploadCard key={`upload-${role}`} title="Source File" onLoaded={handleFirstLoaded} />
      </div>
    );
  }

  // ── exactly one file: the usual preview, plus "Add file" ─────────────
  if (files.length === 1) {
    return (
      <>
        {hiddenInputs}
        {(fileError || adding) && (
          <Alert variant={fileError ? "error" : "info"} style={{ marginBottom: 12 }}>
            {fileError || "Reading file…"}
          </Alert>
        )}
        <DatasetPreviewCard
          dataset={dataset}
          onReplaceFile={() => setShowUploadAgain(true)}
          onAddFile={openAdd}
          addFileDisabled={adding}
        />
      </>
    );
  }

  // ── two or more files: list, join settings, diagnostics, combined preview ─
  return (
    <div className="ct-col">
      {hiddenInputs}

      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Source files</h3>
          <span className="ct-card__spacer" />
          <span className="ct-card__hint">
            {files.length} of {MAX_JOIN_FILES} · {FAMILY_LABEL[files[0].family]} only
          </span>
        </div>
        <div className="ct-card__body mf-file-list">
          {files.map((entry, index) => (
            <div className="ct-file-row" key={entry.id}>
              <span className="mf-file-index mono">{index + 1}</span>
              <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
              <span className="ct-file-row__name" title={entry.filename}>
                {entry.filename}
              </span>
              <span className="ct-file-row__meta mono">
                {entry.rows} rows · {entry.cols} columns
              </span>
              {entry.sheets.length > 1 && (
                <select
                  className="mf-inline-select"
                  aria-label={`Sheet for ${entry.filename}`}
                  value={entry.sheet ?? ""}
                  disabled={busyFileId === entry.id}
                  onChange={(e) => handleSheetChange(entry.id, e.target.value)}
                >
                  {entry.sheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              )}
              <span className="ct-card__spacer" />
              {busyFileId === entry.id && <span className="ct-card__hint">Reading…</span>}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  replaceTargetRef.current = entry.id;
                  replaceInputRef.current?.click();
                }}
              >
                <RefreshCw size={13} aria-hidden /> Replace
              </Button>
              <button
                type="button"
                className="mf-icon-btn"
                title={`Remove ${entry.filename}`}
                aria-label={`Remove ${entry.filename}`}
                onClick={() => handleRemove(entry.id)}
              >
                <X size={14} aria-hidden />
              </button>
            </div>
          ))}

          <div className="mf-add-row">
            <Button type="button" variant="ghost" size="sm" onClick={openAdd} disabled={atCap || adding}>
              <Plus size={14} aria-hidden /> {adding ? "Reading file…" : "Add file"}
            </Button>
            <span className="ct-card__hint">
              {atCap
                ? `Limit reached — at most ${MAX_JOIN_FILES} files per source.`
                : `Each added file is joined onto the files above it. Same type only (${FAMILY_LABEL[files[0].family]}).`}
            </span>
          </div>
          {fileError && <Alert variant="error">{fileError}</Alert>}
        </div>
      </section>

      <section className="ct-card">
        <div
          className="ct-card__head ct-card__head--toggle"
          role="button"
          tabIndex={0}
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen((o) => !o)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setSettingsOpen((o) => !o);
            }
          }}
        >
          <Chevron open={settingsOpen} />
          <h3 className="ct-card__title">Join settings &amp; result</h3>
          <span className="ct-card__spacer" />
          {!settingsOpen && needsReview && (
            <Badge variant="warning" dot>
              Needs review
            </Badge>
          )}
          {!settingsOpen && (
            <span className="ct-card__hint">
              {files
                .slice(1)
                .map((f, i) => {
                  const s = config?.steps?.[i];
                  return s ? `File ${i + 2} on ${s.left_column}${s.left_column !== s.right_column ? ` ↔ ${s.right_column}` : ""} (${s.how})` : `File ${i + 2}: key not set`;
                })
                .join(" · ")}
              {current ? ` · ${current.rows} rows out` : ""}
            </span>
          )}
        </div>
        {settingsOpen && (
          <>
            <div className="ct-card__body mf-steps">
              {files.slice(1).map((entry, i) => {
                const index = i + 1;
                const step = stepsById[entry.id] ?? defaultStep(files, index);
                const common = commonColumns(files, index);
                const priorFiles = files.slice(0, index);
                const leftOptions = priorFiles.flatMap((f, fi) =>
                  f.columns.map((c) => ({ value: JSON.stringify([f.id, c]), label: `File ${fi + 1} · ${c}` })),
                );
                return (
                  <div className="mf-step" key={entry.id}>
                    <div className="mf-step__head">
                      <span className="mf-step__title">
                        Join {index} · File {index + 1} <span className="mono">({entry.filename})</span> onto{" "}
                        {index === 1 ? "File 1" : `Files 1–${index}`}
                      </span>
                      <span className="ct-card__spacer" />
                      <div className="mf-segment" role="group" aria-label="Match columns by">
                        <button
                          type="button"
                          className={step.mode === "common" ? "is-active" : ""}
                          disabled={common.length === 0}
                          title={common.length === 0 ? "The files share no column names" : undefined}
                          onClick={() => updateStep(entry.id, { mode: "common" })}
                        >
                          Same column name
                        </button>
                        <button
                          type="button"
                          className={step.mode === "manual" ? "is-active" : ""}
                          onClick={() => updateStep(entry.id, { mode: "manual" })}
                        >
                          Pick a column from each file
                        </button>
                      </div>
                    </div>

                    <div className="mf-step__grid">
                      {step.mode === "common" ? (
                        <Select
                          label="Join key"
                          value={step.commonColumn}
                          placeholder="Choose the shared column…"
                          options={common.map((c) => ({ value: c, label: c }))}
                          onChange={(e) => updateStep(entry.id, { commonColumn: e.target.value })}
                        />
                      ) : (
                        <div className="mf-pair">
                          <Select
                            label={index === 1 ? "Column from File 1" : `Column from Files 1–${index}`}
                            value={step.leftColumn ? JSON.stringify([step.leftId, step.leftColumn]) : ""}
                            placeholder="Choose a column…"
                            options={leftOptions}
                            onChange={(e) => {
                              const [leftId, leftColumn] = JSON.parse(e.target.value);
                              updateStep(entry.id, { leftId, leftColumn });
                            }}
                          />
                          <span className="mf-pair__arrow" aria-hidden>
                            ↔
                          </span>
                          <Select
                            label={`Column from File ${index + 1}`}
                            value={step.rightColumn}
                            placeholder="Choose a column…"
                            options={entry.columns.map((c) => ({ value: c, label: c }))}
                            onChange={(e) => updateStep(entry.id, { rightColumn: e.target.value })}
                          />
                        </div>
                      )}
                      <Select
                        label="Join type"
                        value={step.how}
                        options={JOIN_TYPE_OPTIONS}
                        onChange={(e) => updateStep(entry.id, { how: e.target.value })}
                      />
                      <fieldset className="mf-sort">
                        <legend>Sort by this key</legend>
                        {["asc", "desc"].map((direction) => (
                          <label key={direction}>
                            <input
                              type="checkbox"
                              checked={sort?.rightId === entry.id && sort.direction === direction}
                              onChange={() => toggleSort(entry.id, direction)}
                            />
                            {direction === "asc" ? "Ascending" : "Descending"}
                          </label>
                        ))}
                      </fieldset>
                    </div>

                    <p className="mf-step__note">
                      {step.auto
                        ? `Only one column name is shared (${step.commonColumn}), so the files are joined on it automatically.`
                        : common.length === 0
                          ? "These files share no column names — pick the key column from each side."
                          : step.mode === "common" && common.length > 1
                            ? `${common.length} column names are shared — choose which one identifies a row.`
                            : "Key values are matched ignoring surrounding spaces and letter case."}
                    </p>
                  </div>
                );
              })}
              <p className="mf-step__note">
                No sort selected keeps source file order. A date-like key is sorted chronologically, a numeric one numerically.
              </p>
            </div>
            {current && (
              <>
                <div className="mf-subhead">
                  <h3 className="ct-card__title">Join result</h3>
                  <span className="ct-card__spacer" />
                  {preview.loading && <span className="ct-card__hint">Updating…</span>}
                </div>
                <div className="ct-card__body ct-card__body--flush ct-table-wrap">
                  <table className="ct-table">
                    <thead>
                      <tr>
                        <th>Join</th>
                        <th>Key</th>
                        <th>Type</th>
                        <th>Rows in</th>
                        <th>Matched</th>
                        <th>Unmatched</th>
                        <th>Missing key</th>
                        <th>Rows out</th>
                      </tr>
                    </thead>
                    <tbody>
                      {current.steps.map((s) => (
                        <tr key={s.step}>
                          <td>File {s.step + 2}</td>
                          <td className="mono">
                            {s.left_label} ↔ {s.right_label}
                            {s.matched_as_dates ? " (as dates)" : ""}
                          </td>
                          <td>{s.how}</td>
                          <td className="mono">
                            {s.left_rows} · {s.right_rows}
                          </td>
                          <td className="mono">
                            {s.matched_left_rows} · {s.matched_right_rows}
                          </td>
                          <td className="mono">
                            {s.left_unmatched} {s.left_unmatched_kept ? "kept" : "not kept"} · {s.right_unmatched}{" "}
                            {s.right_unmatched_kept ? "kept" : "not kept"}
                          </td>
                          <td className="mono">
                            {s.left_missing_key} · {s.right_missing_key}
                          </td>
                          <td className="mono">{s.result_rows}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="ct-card__body mf-result-notes">
                  <p className="mf-step__note">
                    Pairs read <em>left · right</em>.{" "}
                    {current.sort
                      ? `Sorted ${current.sort.direction === "asc" ? "ascending" : "descending"} by ${current.sort.column}${
                          current.sort.kind === "date" ? " — parsed as dates" : current.sort.kind === "numeric" ? " — numerically" : ""
                        }.`
                      : "Rows keep source file order."}
                  </p>
                  {current.renamed_columns.length > 0 && (
                    <p className="mf-step__note">
                      Renamed to avoid overwriting a same-named column:{" "}
                      {current.renamed_columns.map((r) => `${r.from} → ${r.to} (File ${r.file + 1})`).join(", ")}.
                    </p>
                  )}
                  {current.steps
                    .filter((s) => s.matched_left_rows === 0)
                    .map((s) => (
                      <Alert key={`nomatch-${s.step}`} variant="warning" title={`Join ${s.step + 1}: no key values matched`}>
                        None of the {s.left_label} values match {s.right_label}. Check that this is the right key pair
                        {s.how === "inner" ? " — an inner join with no matches produces an empty dataset." : "."}
                      </Alert>
                    ))}
                  {current.steps
                    .filter((s) => s.extra_rows_from_duplicates > 0)
                    .map((s) => (
                      <Alert key={s.step} variant="warning" title={`Join ${s.step + 1}: duplicate key values multiplied rows (${s.relationship})`}>
                        {s.left_duplicate_key_rows > 0 && `${s.left_duplicate_key_rows} rows on the left share a key value. `}
                        {s.right_duplicate_key_rows > 0 && `${s.right_duplicate_key_rows} rows in File ${s.step + 2} share a key value. `}
                        Rows before: {s.left_rows} (left) · {s.right_rows} (File {s.step + 2}). Rows after: {s.result_rows} —{" "}
                        {s.extra_rows_from_duplicates} extra row{s.extra_rows_from_duplicates === 1 ? "" : "s"} created by repeating
                        matched rows. Check that this key really identifies one row per record.
                      </Alert>
                    ))}
                  {extraRows > 0 && (
                    <label className="mf-ack">
                      <input
                        type="checkbox"
                        checked={ackSig === signature}
                        onChange={(e) => setAckSig(e.target.checked ? signature : null)}
                      />
                      I&apos;ve reviewed the duplicate keys — use the joined rows as they are.
                    </label>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </section>

      {!config && (
        <Alert variant="info">Choose a join key for every added file to see the combined result.</Alert>
      )}
      {config && preview.loading && !current && <Alert variant="info">Joining files…</Alert>}
      {config && preview.error && preview.sig === signature && (
        <Alert variant="error" title="Join failed">
          {preview.error}
        </Alert>
      )}

      {current && (
        <>
          {current.missing_key_groups.length > 0 && (
            <section className="ct-card">
              <div className="ct-card__head">
                <h3 className="ct-card__title">Unmatched — missing key</h3>
                <span className="ct-card__spacer" />
                <span className="ct-card__hint">
                  {current.missing_key_groups.reduce((n, g) => n + g.count, 0)} rows with a blank key never match
                </span>
              </div>
              <div className="ct-card__body ct-card__body--stack">
                {current.missing_key_groups.map((g) => (
                  <div key={`${g.step}-${g.side}`}>
                    <p className="mf-step__note">
                      <strong>
                        Join {g.step + 1} · {g.label}
                      </strong>{" "}
                      — {g.count} row{g.count === 1 ? "" : "s"} with a blank <span className="mono">{g.key_column}</span>
                      {g.kept ? ", kept in the result as unmatched" : ", excluded from the result"}
                      {g.count > g.preview.length ? ` (first ${g.preview.length} shown)` : ""}
                    </p>
                    <PreviewTable columns={g.columns} rows={g.preview} />
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="ct-card">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Combined preview</h3>
              <span className="ct-card__spacer" />
              <span className="ct-card__hint">
                First {current.preview.length} of {current.rows} rows · {current.cols} columns
              </span>
              {isApplied ? (
                <Badge variant="success" dot>
                  Applied
                </Badge>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  onClick={handleApply}
                  disabled={applying || preview.loading || needsAck}
                  title={needsAck ? "Confirm the duplicate-key warning first" : undefined}
                >
                  {applying ? "Applying…" : "Use combined dataset"}
                </Button>
              )}
            </div>
            <div className="ct-card__body ct-card__body--flush">
              <PreviewTable columns={current.columns} rows={current.preview} />
            </div>
          </section>
          {applyError && (
            <Alert variant="error" title="Could not build the combined file">
              {applyError}
            </Alert>
          )}
          {pending && !applyError && (
            <p className="mf-step__note">
              Continue unlocks once the combined dataset is applied
              {appliedSig ? " — the settings changed since it was last applied." : "."}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default MultiFileSourcePanel;
