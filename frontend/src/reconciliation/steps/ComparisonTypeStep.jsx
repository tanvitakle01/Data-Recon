import { useMemo, useRef, useState } from "react";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import { Badge, Select, Button, Alert } from "@bristlecone/canopy";
import { Upload, FileSpreadsheet, X, Loader2 } from "lucide-react";

// The Dataset Type list is no longer static: it is the interface list read
// from the uploaded workbook's "Interfaces" index sheet (see
// backend/recon_engine/interface_index.py). Until a workbook is parsed there
// are no dataset types to offer at all.
//
// This deploy is mapping-sheet-driven only: there is no live connection to
// read a system's metadata from, so the sheet is parsed and handed to the
// Mapping step, and the connectors themselves are chosen by hand on the
// Source/Target steps. Nothing on this page calls out to a live system.

const SHEET_ACCEPT = ".xlsx,.xls,.csv";

// Suffix shown on an interface that can't be run because its worksheet
// couldn't be resolved. It stays LISTED (greyed out) rather than silently
// dropped, so an incomplete workbook is visible instead of mysterious.
function brokenReason(iface) {
  if (iface.match === "ambiguous") {
    return `matches ${iface.candidates?.length ?? 2} sheets`;
  }
  return "sheet missing";
}

// ── Upload (empty state) ──────────────────────────────────────────────────
// A single compact dropzone row — icon, copy, button — so the card carries
// the workbook's interface list rather than being dominated by the picker.
// Drag/drop still works across the whole row; the hint says so in the caption.
function UploadDropzone({ onPick, onDropFile, loading }) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div
      className={`wizard-upload-row ${dragOver ? "is-dragover" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) onDropFile(file);
      }}
    >
      <Upload className="wizard-upload-row__icon" aria-hidden />
      <div className="wizard-upload-row__text">
        <p className="wizard-upload-row__title">Upload your mapping sheet</p>
        <p className="wizard-upload-row__hint">
          Drag &amp; drop, or choose a file (.xlsx, .xls, .csv)
        </p>
      </div>
      <Button variant="primary" size="sm" onClick={onPick} loading={loading} disabled={loading}>
        {loading ? "Reading…" : "Upload"}
      </Button>
    </div>
  );
}

function ComparisonTypeStep() {
  const { state, dispatch } = useWizard();
  const selectedId = state.comparisonType?.id ?? "";
  const interfaceIndex = state.interfaceIndex;

  const interfaces = interfaceIndex?.interfaces ?? [];
  const selectedInterface = interfaces.find((i) => i.id === selectedId) ?? null;
  // A workbook whose index lists exactly one interface (or a single-sheet
  // upload) has nothing to choose — the dropdown is skipped and the interface
  // is auto-selected on upload.
  const singleInterface = interfaces.length === 1;
  // Specifically the one-sheet upload: the user sent a single interface's
  // sheet instead of the whole project workbook, so that sheet IS the dataset
  // and there is no "rest of the workbook" being discarded.
  const singleSheet = Boolean(interfaceIndex?.single_sheet);

  const sheetInputRef = useRef(null);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetError, setSheetError] = useState(null);
  // The chosen interface's own sheet being read. Separate from sheetLoading
  // (the workbook index read) because they are separate phases: the index
  // read only ever yields the interface list.
  const [sliceLoading, setSliceLoading] = useState(false);

  // Slice ONE interface out of the workbook and parse only that slice
  // (deterministic, scoped to that worksheet).
  const selectInterface = async (iface, index = interfaceIndex) => {
    if (!iface) {
      dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
      return;
    }
    dispatch({
      type: WizardActions.SET_COMPARISON_TYPE,
      comparisonType: { id: iface.id, label: iface.record },
    });

    const file = index?.file;
    // A broken interface has no worksheet to slice — it is selectable-proof in
    // the dropdown, so this only guards a workbook re-read losing the File.
    if (!file || !iface.sheet) return;

    setSheetError(null);
    setSliceLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("sheet_name", iface.sheet);
      const parseRes = await api.post("/api/recon/mapping-sheet/parse", formData);
      // Feeds the Mapping step: the Transformations Editor's "draft from
      // description" context, and the sequential AI mapping-resolution chain
      // (TransformationSpecStep) both read `transformationSpec.parsedMappingSheet`.
      dispatch({
        type: WizardActions.SET_PARSED_MAPPING_SHEET,
        parsedMappingSheet: parseRes.data,
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string"
          ? detail
          : `Could not read the "${iface.record}" interface.`
      );
    } finally {
      setSliceLoading(false);
    }
  };

  const handleChange = (event) => {
    const id = event.target.value;
    selectInterface(interfaces.find((i) => i.id === id) ?? null);
  };

  // Upload reads the workbook's INTERFACE INDEX only — no field table is read
  // and nothing is interpreted yet. The interface list it returns becomes the
  // Dataset Type options; the chosen one's sheet is sliced in selectInterface.
  const handleSheetFile = async (file) => {
    if (!file) return;
    setSheetError(null);
    setSheetLoading(true);
    // A different workbook invalidates the previous interface list and the
    // dataset type chosen from it.
    dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post("/api/recon/mapping-sheet/interfaces", formData);
      // The File is retained so selecting a dataset type can issue the scoped
      // parse without asking for the workbook again.
      const index = { ...res.data, file };
      dispatch({ type: WizardActions.SET_INTERFACE_INDEX, interfaceIndex: index });
      // Records the workbook itself (name/size) on transformationSpec — the
      // Mapping step (Results export, the Transformations Editor's AI context)
      // reads this. Also resets parsedMappingSheet, which selectInterface below
      // repopulates once the chosen interface's sheet is parsed.
      dispatch({
        type: WizardActions.SET_MAPPING_SHEET,
        mappingSheet: { name: file.name, size: file.size, file },
      });

      const list = res.data.interfaces ?? [];
      if (list.length === 1 && list[0].status === "ok") {
        await selectInterface(list[0], index);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string" ? detail : "Could not read the mapping workbook."
      );
    } finally {
      setSheetLoading(false);
      if (sheetInputRef.current) sheetInputRef.current.value = "";
    }
  };

  const clearSheet = () => {
    dispatch({ type: WizardActions.CLEAR_INTERFACE_INDEX });
    dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
    dispatch({ type: WizardActions.SET_MAPPING_SHEET, mappingSheet: null });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "source" });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "target" });
    setSheetError(null);
    if (sheetInputRef.current) sheetInputRef.current.value = "";
  };

  // Both gates, not just the dataset type: the run needs a parsed workbook to
  // have produced the interface AND that interface to have been chosen.
  const canContinue = useMemo(
    () => Boolean(state.comparisonType) && Boolean(state.interfaceIndex),
    [state.comparisonType, state.interfaceIndex]
  );

  const fileMetaText = interfaceIndex
    ? [
        interfaceIndex.file?.size != null
          ? `${Math.round(interfaceIndex.file.size / 1024)} KB`
          : null,
        `${interfaces.length} ${interfaceIndex.indexed ? "interface" : "sheet"}${interfaces.length === 1 ? "" : "s"}`,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <StepShell stepKey="comparisonType" canContinue={canContinue}>
      <div className="ct-grid">
        {/* ══ Left column: Mapping sheet ══ */}
        <div className="ct-col">
          <section className="ct-card ct-card--tint-blue">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Mapping sheet</h3>
            </div>
            <div className="ct-card__body">
              <input
                ref={sheetInputRef}
                type="file"
                accept={SHEET_ACCEPT}
                style={{ display: "none" }}
                onChange={(e) => handleSheetFile(e.target.files?.[0] ?? null)}
              />

              {!interfaceIndex ? (
                <>
                  <p className="wizard-field__help" style={{ marginTop: 0 }}>
                    Upload a mapping workbook to read its interfaces. A single-sheet file is
                    taken as one interface directly.
                  </p>
                  <UploadDropzone
                    onPick={() => sheetInputRef.current?.click()}
                    onDropFile={handleSheetFile}
                    loading={sheetLoading}
                  />
                </>
              ) : (
                <div className="ct-mapping-body">
                  <div className="ct-file-row">
                    <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
                    <span className="ct-file-row__name" title={interfaceIndex.filename}>
                      {interfaceIndex.filename ?? "mapping sheet"}
                    </span>
                    {fileMetaText && <span className="ct-file-row__meta mono">{fileMetaText}</span>}
                    <span className="ct-card__spacer" />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => sheetInputRef.current?.click()}
                      disabled={sheetLoading}
                    >
                      {sheetLoading ? (
                        <Loader2 size={12} className="animate-spin" aria-hidden />
                      ) : (
                        "Replace"
                      )}
                    </Button>
                    <Button variant="outline" size="sm" onClick={clearSheet} disabled={sheetLoading}>
                      <X size={12} aria-hidden />
                      Remove
                    </Button>
                  </div>

                  {sliceLoading && (
                    <p className="wizard-field__help" style={{ marginTop: 0 }}>
                      <Loader2 size={12} className="animate-spin" aria-hidden /> Reading the
                      selected interface&apos;s sheet…
                    </p>
                  )}

                  {/* What the index read itself found wrong: no index sheet, a
                      duplicated IBP Record, interfaces with no worksheet. */}
                  {(interfaceIndex.warnings ?? []).map((warning, i) => (
                    <Alert variant="warning" key={i}>
                      {warning}
                    </Alert>
                  ))}
                </div>
              )}

              {sheetError && <Alert variant="error">{sheetError}</Alert>}
            </div>
          </section>

          {/* The interface-scoping contract, stated plainly: exactly one
              worksheet reaches the Mapping step. For a workbook that means the
              rest is discarded here; for a one-sheet upload there is no rest,
              so claiming a discard would be untrue. */}
          {selectedInterface?.sheet && (
            <section className="ct-card">
              <div className="ct-card__body ct-scope-note">
                <FileSpreadsheet className="ct-scope-note__icon" aria-hidden />
                <p className="ct-scope-note__text">
                  {singleSheet ? (
                    <>
                      {interfaceIndex.filename ?? "This upload"} holds a single sheet, so it is
                      the dataset: <strong>&ldquo;{selectedInterface.sheet}&rdquo;</strong> is
                      the only worksheet carried forward.
                    </>
                  ) : (
                    <>
                      Only the <strong>&ldquo;{selectedInterface.sheet}&rdquo;</strong> sheet is
                      extracted and carried forward. The rest of{" "}
                      {interfaceIndex.filename ?? "the workbook"} is discarded at this step.
                    </>
                  )}
                </p>
              </div>
            </section>
          )}
        </div>

        {/* ══ Right column: Dataset type ══ */}
        <div className="ct-col">
          <section className="ct-card">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Dataset type</h3>
            </div>
            <div className="ct-card__body ct-card__body--stack">
              <div className="wizard-field" style={{ maxWidth: "none" }}>
                <label className="wizard-field__label" htmlFor="comparison-type-select">
                  Interface
                </label>
                {singleInterface ? (
                  // One interface in the workbook — there is no choice to make,
                  // so it's stated rather than offered as a dropdown of one.
                  <div className="ct-file-row">
                    <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
                    <span className="ct-file-row__name">{interfaces[0].record}</span>
                  </div>
                ) : (
                  <Select
                    id="comparison-type-select"
                    value={selectedId}
                    onChange={handleChange}
                    disabled={!interfaceIndex || sliceLoading}
                    options={[
                      {
                        value: "",
                        label: interfaceIndex
                          ? "Select a dataset type…"
                          : "Parse a mapping sheet first",
                      },
                      // Interfaces whose worksheet couldn't be resolved stay
                      // listed but unselectable — an incomplete workbook should
                      // be visible, not silently shortened.
                      ...interfaces.map((iface) => ({
                        value: iface.id,
                        label:
                          iface.status === "ok"
                            ? iface.record
                            : `${iface.record} — ${brokenReason(iface)}`,
                        disabled: iface.status !== "ok",
                      })),
                    ]}
                  />
                )}
                {state.comparisonType && (
                  <div className="wizard-dataset-summary">
                    <Badge variant="success">Selected</Badge>
                    <span>{state.comparisonType.label}</span>
                  </div>
                )}
                <p className="wizard-field__help">
                  Upload the source and target data on the next two steps.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </StepShell>
  );
}

export default ComparisonTypeStep;
