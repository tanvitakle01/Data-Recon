// App-wide assistant bot — a large floating launcher (bigger than Mapping
// Review's fab, and visible on every authenticated page since it's mounted
// once in AppLayout) that slides a chat panel out from the right, 45vw wide
// and full viewport height. The input row supports attaching files three
// ways — the "+" button (native file picker), dragging files anywhere onto
// the open panel, and pasting files from the clipboard.
//
// Talks to POST /api/chat/message: the backend classifies whether the
// message + attachments describe a reconciliation request and, if so, which
// role each file plays (mapping sheet vs. source/target data), then kicks
// off the matching Auto-mode pipeline run (see
// backend/recon_engine/chat_assistant/orchestrator.py). This component polls
// GET /api/recon/auto-run/{id}/status for progress, renders the resolver
// bot's question inline if the run pauses for input, and on completion shows
// a results card, a bot-attached results Excel workbook, and floating
// suggestion pills ("View Insights" / "Run next reconciliation") above the
// input row.
import { useEffect, useRef, useState } from "react";
import { ArrowRight, BarChart2, Bot, Check, FileText, Layers, Paperclip, Plus, Send, X } from "lucide-react";
import api from "../../services/api";
import ShortId from "../ShortId";
import styles from "./assistantBot.module.css";

const GREETING = {
  id: "greeting",
  from: "bot",
  text: "Hello! I'm your Data Reconciliation assistant. Ask me to reconcile a mapping sheet or a source/target dataset and I'll take it from there.",
};

const POLL_INTERVAL_MS = 1500;

// Typed while the last bot message shows a resumable ("batch N of M")
// interruption — any of these (case-insensitive, whitespace-trimmed) resumes
// that run instead of being sent through the normal chat/intent flow. Any
// OTHER typed text still goes through the normal flow unchanged.
const RETRY_KEYWORDS = new Set(["retry", "continue", "resume", "yes"]);

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function makeAttachment(file) {
  const isImage = file.type.startsWith("image/");
  return {
    id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
    file,
    name: file.name,
    size: file.size,
    isImage,
    previewUrl: isImage ? URL.createObjectURL(file) : null,
  };
}

function AttachmentChip({ attachment, onRemove, onDownload }) {
  // Purely presentational: an attachment the user is about to send (still
  // removable) reads as an "upload" (accent tint); one the bot handed back
  // (downloadable) reads as a "download" (info tint) — same distinction the
  // Data Sources / Insights pages already use for outbound vs. inbound files.
  const tone = onDownload ? styles.attachmentIconDownload : styles.attachmentIconUpload;
  return (
    <div className={styles.attachmentChip}>
      {attachment.isImage ? (
        <img src={attachment.previewUrl} alt={attachment.name} className={styles.attachmentThumb} />
      ) : (
        <span className={`${styles.attachmentIcon} ${tone}`}>
          <FileText size={16} />
        </span>
      )}
      <div className={styles.attachmentMeta}>
        <span className={styles.attachmentName} title={attachment.name}>
          {attachment.name}
        </span>
        <span className={styles.attachmentSize}>
          {attachment.size != null ? formatFileSize(attachment.size) : "Download"}
        </span>
      </div>
      {onDownload && (
        <button
          type="button"
          className={styles.attachmentRemove}
          onClick={() => onDownload(attachment)}
          aria-label={`Download ${attachment.name}`}
          title="Download"
        >
          <FileText size={12} />
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          className={styles.attachmentRemove}
          onClick={() => onRemove(attachment.id)}
          aria-label={`Remove ${attachment.name}`}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

const STATUS_LABELS = {
  running: "Running reconciliation…",
  waiting_for_input: "Needs your input",
  completed: "Reconciliation complete",
  failed: "Reconciliation failed",
  cancelling: "Cancelling…",
  cancelled: "Reconciliation cancelled",
};

// Mirrors backend/recon_engine/auto_pipeline/state.py's STEP_NAMES exactly —
// keep the two in sync if either changes, since milestoneDone below relies on
// this order to tell "already passed" from "not reached yet".
const STEP_LABELS = {
  select_source: "Selecting source system…",
  select_target: "Selecting target system…",
  resolve_schema: "Resolving schema & candidate keys…",
  compile_contract: "Compiling reconciliation contract…",
  plan_date_batches: "Planning batches…",
  run_batches: "Running batches…",
  finalize: "Finalizing results…",
};
const STEP_ORDER = Object.keys(STEP_LABELS);

// The 7 backend steps read as 3 user-facing milestones (each "done" once the
// run has moved past the named step) plus whichever step is currently
// active. Everything from "run_batches" on is shown by BatchProgress instead
// (see StepChecklist) since that step processes many batches sequentially
// rather than completing once.
const MILESTONES = [
  { throughStep: "select_target", label: "Source & target selected" },
  { throughStep: "compile_contract", label: "Schema resolved & contract compiled" },
  { throughStep: "plan_date_batches", label: "Batches planned" },
];

function milestoneDone(currentStep, throughStep, status) {
  if (status === "completed") return true;
  const curIdx = STEP_ORDER.indexOf(currentStep);
  const throughIdx = STEP_ORDER.indexOf(throughStep);
  if (curIdx === -1 || throughIdx === -1) return false;
  return curIdx > throughIdx;
}

// Mirrors backend/recon_engine/auto_pipeline/nodes.py's `_report_batch_stage`
// stage names exactly — keep the two in sync if either changes.
const BATCH_STAGE_ORDER = ["fetching_source", "fetching_target", "pairing_values", "reconciling", "completed"];
const BATCH_STAGE_LABELS = {
  fetching_source: "Fetching source data…",
  fetching_target: "Fetching target data…",
  pairing_values: "Pairing values across systems…",
  reconciling: "Reconciling batch…",
  completed: "Batch reconciled",
};

// The same 4-stage story as the old single-pass MILESTONES (source, target,
// keys, reconcile) but scoped to ONE batch — replayed fresh for every batch
// in the plan, since each batch reconciles its own date-windowed slice of
// source/target independently (see nodes.py's `_do_run_batches`).
const BATCH_MILESTONES = [
  { throughStage: "fetching_source", label: "Source data fetched" },
  { throughStage: "fetching_target", label: "Target data fetched" },
  { throughStage: "pairing_values", label: "Values paired" },
  { throughStage: "reconciling", label: "Batch reconciled" },
];

function batchMilestoneDone(stage, throughStage) {
  const curIdx = BATCH_STAGE_ORDER.indexOf(stage);
  const throughIdx = BATCH_STAGE_ORDER.indexOf(throughStage);
  if (curIdx === -1 || throughIdx === -1) return false;
  return curIdx > throughIdx;
}

// Live "N/M batches done" + the current batch's own source/target/pairing/
// reconcile checklist — rendered in place of the generic step-in-progress
// line while `current_step === "run_batches"`. Derived entirely from
// `run.batch_progress`, already polled from GET /api/recon/auto-run/{id}/status.
function BatchProgress({ bp }) {
  const stage = bp.stage || "fetching_source";
  const batchesDone = bp.batches_completed ?? bp.batch_index;
  return (
    <>
      <div className={styles.batchProgressHeader}>
        <span className={styles.batchProgressCounter}>
          {batchesDone}/{bp.batch_count} batches done
        </span>
        <span className={styles.batchProgressLabel} title={bp.batch_label}>
          Batch {bp.batch_index + 1} of {bp.batch_count} — {bp.batch_label}
        </span>
      </div>
      {BATCH_MILESTONES.map((m) => {
        const done = batchMilestoneDone(stage, m.throughStage);
        return (
          <div key={m.label} className={styles.stepRow}>
            <span className={`${styles.stepDot}${done ? ` ${styles.stepDotDone}` : ""}`}>
              {done && <Check size={9} strokeWidth={3.5} />}
            </span>
            <span className={`${styles.stepLabel}${done ? ` ${styles.stepLabelDone}` : ""}`}>{m.label}</span>
          </div>
        );
      })}
      {stage !== "completed" && (
        <div className={styles.stepActive}>
          <span className={styles.stepPulse}>
            <span className={styles.stepPulseDot} />
            <span className={styles.stepPulseDot} />
          </span>
          <span className={styles.stepActiveLabel}>{BATCH_STAGE_LABELS[stage] || "Working…"}</span>
        </div>
      )}
    </>
  );
}

// Cumulative progress checklist for a run's bot message: milestones already
// passed show a checkmark, and — while actively running — the specific
// granular step in progress shows as an animated line below them. Once the
// run reaches "run_batches", that line is replaced by BatchProgress's own
// per-batch checklist and batch counter. Derived entirely from
// `current_step`/`status`/`batch_progress`, already polled from
// GET /api/recon/auto-run/{id}/status — no new data needed.
function StepChecklist({ run }) {
  const currentStep = run.current_step;
  const status = run.status;
  const bp = run.batch_progress;
  const inBatchLoop = status === "running" && currentStep === "run_batches" && !!bp;
  return (
    <div className={styles.stepChecklist}>
      {MILESTONES.map((m) => {
        const done = milestoneDone(currentStep, m.throughStep, status);
        return (
          <div key={m.label} className={styles.stepRow}>
            <span className={`${styles.stepDot}${done ? ` ${styles.stepDotDone}` : ""}`}>
              {done && <Check size={9} strokeWidth={3.5} />}
            </span>
            <span className={`${styles.stepLabel}${done ? ` ${styles.stepLabelDone}` : ""}`}>{m.label}</span>
          </div>
        );
      })}
      {inBatchLoop && <BatchProgress bp={bp} />}
      {status === "running" && currentStep && !inBatchLoop && (
        <div className={styles.stepActive}>
          <span className={styles.stepPulse}>
            <span className={styles.stepPulseDot} />
            <span className={styles.stepPulseDot} />
          </span>
          <span className={styles.stepActiveLabel}>{STEP_LABELS[currentStep] || "Working…"}</span>
        </div>
      )}
    </div>
  );
}

function ResultBadges({ summary }) {
  if (!summary) return null;
  const tones = [
    ["match", summary.match ?? summary.matched],
    ["missing", summary.mismatch],
    ["medium", summary.quantity_mismatch],
  ];
  return (
    <div className={styles.resultBadges}>
      {tones
        .filter(([, value]) => value != null)
        .map(([tone, value]) => (
          <span key={tone} className={`status-badge status-badge--${tone}`}>
            <span className="status-badge__dot" />
            {value}
          </span>
        ))}
    </div>
  );
}

function RunProgress({ run, onResolve }) {
  const [resolveText, setResolveText] = useState("");
  if (!run) return null;

  // The short-form run id (see components/ShortId.jsx) is shown alongside
  // every status — waiting/completed/failed/running alike — so a user can
  // reference or copy this specific run's full id from the chat at any point
  // in its lifecycle, not just once it finishes.
  const idBadge = run.graphRunId && (
    <div className={styles.runIdBadge}>
      <ShortId value={run.graphRunId} prefix="Run " />
    </div>
  );

  if (run.status === "waiting_for_input" && run.interrupt) {
    return (
      <div className={styles.resolver}>
        <StepChecklist run={run} />
        <div className={styles.resolverEyebrowRow}>
          <span className={styles.resolverEyebrow}>Needs your input</span>
          {idBadge}
        </div>
        <p className={styles.resolverMessage}>{run.interrupt.message}</p>
        {run.interrupt.options?.length > 0 && (
          <div className={styles.resolverChips}>
            {run.interrupt.options.map((opt) => (
              <button
                key={opt}
                type="button"
                className={styles.resolverChip}
                onClick={() => onResolve(opt)}
              >
                {opt}
              </button>
            ))}
          </div>
        )}
        <div className={styles.resolverInputRow}>
          <input
            className={styles.resolverInput}
            placeholder="Or type an answer…"
            value={resolveText}
            onChange={(e) => setResolveText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && resolveText.trim()) {
                onResolve(resolveText.trim());
                setResolveText("");
              }
            }}
          />
          <ArrowRight size={15} className={styles.resolverInputIcon} />
        </div>
      </div>
    );
  }

  if (run.status === "completed") {
    return (
      <>
        {idBadge}
        <ResultBadges summary={run.result?.result_summary?.summary} />
      </>
    );
  }

  if (run.status === "failed") {
    if (run.resumable) {
      const bp = run.batch_progress;
      return (
        <>
          {idBadge}
          <p className={styles.runInterrupted}>
            {bp
              ? `Reconciliation was interrupted after completing ${bp.batches_completed ?? bp.batch_index} of ` +
                `${bp.batch_count} batches. It can continue from where it left off.`
              : "Reconciliation was interrupted. It can continue from where it left off."}
          </p>
        </>
      );
    }
    return (
      <>
        {idBadge}
        <p className={styles.runError}>{run.error || "Something went wrong."}</p>
      </>
    );
  }

  return (
    <>
      {idBadge}
      <StepChecklist run={run} />
      {run.status !== "running" && (
        <p className={styles.runStatusLine}>{STATUS_LABELS[run.status] || "Working…"}</p>
      )}
    </>
  );
}

function Message({ message, onResolve, onDownloadAttachment }) {
  const { from, text, attachments, run } = message;
  const isBot = from !== "user";
  const isInterrupt = run?.status === "waiting_for_input";
  const bubbleClasses = [styles.message, isBot ? styles.messageBot : styles.messageUser, isInterrupt ? styles.messageInterrupt : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={`${styles.messageRow}${isBot ? "" : ` ${styles.messageRowUser}`}`}>
      {isBot && (
        <span className={styles.messageAvatar}>
          <Bot size={13} strokeWidth={1.75} />
        </span>
      )}
      <div className={bubbleClasses}>
        {text && <div>{text}</div>}
        {attachments?.length > 0 && (
          <div className={styles.messageAttachments}>
            {attachments.map((a) => (
              <AttachmentChip key={a.id} attachment={a} onDownload={a.downloadUrl ? onDownloadAttachment : undefined} />
            ))}
          </div>
        )}
        {run && <RunProgress run={run} onResolve={(value) => onResolve(message.id, value)} />}
      </div>
    </div>
  );
}

// Floating suggestion pills — shown above the input row (not inside the chat
// bubble) once the most recent bot message's run has completed OR hit a
// resumable batch interruption, so they read as quick next-step affordances
// rather than part of the bot's reply.
function FloatingSuggestions({ run, onViewInsights, onRunNext, onRetry }) {
  if (run?.status === "failed" && run?.resumable) {
    return (
      <div className={styles.floatingSuggestions}>
        <button type="button" className={styles.suggestionPill} onClick={onRetry}>
          Retry reconciliation
        </button>
      </div>
    );
  }
  return (
    <div className={styles.floatingSuggestions}>
      <button type="button" className={styles.suggestionPill} onClick={onViewInsights}>
        <BarChart2 size={14} />
        View Insights
      </button>
      <button type="button" className={styles.suggestionPill} onClick={onRunNext}>
        <Layers size={14} />
        Run next reconciliation
      </button>
    </div>
  );
}

function AssistantBot() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([GREETING]);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [chatState, setChatState] = useState(null);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);
  const fileInputRef = useRef(null);
  const dragDepthRef = useRef(0);
  const pollRef = useRef(null);
  const lastMessage = messages[messages.length - 1];

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    return () => {
      attachments.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => clearTimeout(pollRef.current);
  }, []);

  function updateRunInMessage(messageId, patch) {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, run: { ...m.run, ...patch } } : m))
    );
  }

  function pollRun(messageId, graphRunId) {
    clearTimeout(pollRef.current);
    pollRef.current = setTimeout(async () => {
      try {
        const res = await api.get(`/api/recon/auto-run/${graphRunId}/status`);
        const s = res.data;
        updateRunInMessage(messageId, {
          status: s.status,
          current_step: s.current_step,
          error: s.error,
          result: s.result,
          interrupt: s.interrupt,
          resumable: s.resumable,
          batch_progress: s.batch_progress,
        });
        if (s.status === "running") {
          pollRun(messageId, graphRunId);
        }
      } catch {
        updateRunInMessage(messageId, { status: "failed", error: "Lost connection to the run." });
      }
    }, POLL_INTERVAL_MS);
  }

  // Retry pill tap OR a typed retry keyword while the last message shows a
  // resumable interruption — either way, resumes the SAME graph_run_id from
  // exactly the batch it stopped at (see backend's /retry route), never a
  // brand-new run.
  async function handleRetry(messageId, graphRunId) {
    if (!graphRunId) return;
    try {
      await api.post(`/api/recon/auto-run/${graphRunId}/retry`);
      updateRunInMessage(messageId, { status: "running", error: null, resumable: false });
      pollRun(messageId, graphRunId);
    } catch (err) {
      updateRunInMessage(messageId, {
        error: err?.response?.data?.detail || "Could not retry this reconciliation.",
      });
    }
  }

  async function handleResolve(messageId, value) {
    const message = messages.find((m) => m.id === messageId);
    const graphRunId = message?.run?.graphRunId;
    if (!graphRunId) return;
    try {
      await api.post(`/api/recon/auto-run/${graphRunId}/resolve`, { value });
      updateRunInMessage(messageId, { status: "running", interrupt: null });
      pollRun(messageId, graphRunId);
    } catch (err) {
      updateRunInMessage(messageId, {
        error: err?.response?.data?.detail || "Could not submit that answer.",
      });
    }
  }

  // Shared "fetch a blob, attach it to a chat message" recipe — used by the
  // "View Insights" pill, the auto-attached results workbook, and a
  // text-driven insights reply (see sendMessage's `insights` handling below).
  async function attachBlobToMessage(messageId, { method = "get", url, data, filename, attachmentId }) {
    try {
      const res =
        method === "post"
          ? await api.post(url, data, { responseType: "blob" })
          : await api.get(url, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId
            ? {
                ...m,
                attachments: [
                  ...(m.attachments || []),
                  { id: attachmentId, name: filename, isImage: false, previewUrl: null, downloadUrl: blobUrl },
                ],
              }
            : m
        )
      );
      return true;
    } catch {
      return false;
    }
  }

  // "View Insights" stays inside the chat — it fetches the same structured
  // Insights PDF the Insights page's "Download PDF" button produces and
  // posts it as a new bot message, rather than navigating away from the chat.
  async function handleViewInsights(run) {
    const runId = run?.result?.result_summary?.run_id || run?.result?.run_id;
    if (!runId) return;
    await postInsightsPdf(runId, "Here's the insights report for this run.");
  }

  async function postInsightsPdf(runId, introText) {
    const botMessageId = `b-${Date.now()}`;
    setMessages((prev) => [...prev, { id: botMessageId, from: "bot", text: introText }]);
    const ok = await attachBlobToMessage(botMessageId, {
      method: "post",
      url: "/insights/pdf",
      data: { run_id: runId },
      filename: `insights_${runId}.pdf`,
      attachmentId: `insights-pdf-${runId}`,
    });
    if (!ok) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botMessageId ? { ...m, text: "Couldn't generate the insights report for this run." } : m
        )
      );
    }
  }

  function handleRunNext() {
    setChatState(null);
    setAttachments([]);
    setMessages((prev) => [
      ...prev,
      {
        id: `b-${Date.now()}`,
        from: "bot",
        text: "Ready for the next reconciliation — attach a mapping sheet or source/target data whenever you're ready.",
      },
    ]);
  }

  function handleDownloadAttachment(attachment) {
    const a = document.createElement("a");
    a.href = attachment.downloadUrl;
    a.download = attachment.name;
    a.click();
  }

  // Once a run completes, fetch the same comparison workbook the
  // reconciliation results page's Excel download produces, and attach it to
  // this chat message as a bot-authored download — no new backend endpoint,
  // the existing GET /api/recon/runs/{run_id}/comparison.xlsx route already
  // builds it.
  async function attachResultsExcel(messageId, runId) {
    // The results workbook is a nice-to-have alongside the results — a
    // failure here shouldn't disrupt the already-posted reconciliation results.
    await attachBlobToMessage(messageId, {
      url: `/api/recon/runs/${runId}/comparison.xlsx`,
      filename: `results_${runId}.xlsx`,
      attachmentId: `xlsx-${runId}`,
    });
  }

  // Watches for any message's run just having flipped to "completed": fetches
  // its results workbook exactly once (guarded by whether the message already
  // carries that attachment), and remembers it as the session's last
  // completed run so a later "show me insights" with no run named can still
  // resolve one (see orchestrator.handle_message's INSIGHTS branch, which
  // reads `state.last_completed_run_id`).
  useEffect(() => {
    messages.forEach((m) => {
      if (m.run?.status !== "completed") return;
      const runId = m.run?.result?.result_summary?.run_id || m.run?.result?.run_id;
      if (!runId) return;
      const alreadyAttached = (m.attachments || []).some((a) => a.id === `xlsx-${runId}`);
      if (!alreadyAttached) attachResultsExcel(m.id, runId);
      setChatState((prev) => (prev?.last_completed_run_id === runId ? prev : { ...(prev || {}), last_completed_run_id: runId }));
    });
  }, [messages]);

  function addFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setAttachments((prev) => [...prev, ...files.map(makeAttachment)]);
  }

  function removeAttachment(id) {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
  }

  function handleDragEnter(e) {
    e.preventDefault();
    if (!e.dataTransfer?.types?.includes("Files")) return;
    dragDepthRef.current += 1;
    setDragActive(true);
  }

  function handleDragOver(e) {
    e.preventDefault();
  }

  function handleDragLeave(e) {
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragActive(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);
    addFiles(e.dataTransfer?.files);
  }

  function handlePaste(e) {
    const files = Array.from(e.clipboardData?.items || [])
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      e.preventDefault();
      addFiles(files);
    }
  }

  async function sendMessage() {
    const text = draft.trim();
    if (!text && attachments.length === 0) return;
    if (sending) return;

    // A resumable interruption is showing and no new files were attached —
    // a retry keyword resumes that run instead of going through the normal
    // chat/intent flow (see backend's /retry route). Any other typed text
    // still falls through to the normal flow below.
    if (
      attachments.length === 0 &&
      lastMessage?.run?.status === "failed" &&
      lastMessage.run.resumable &&
      RETRY_KEYWORDS.has(text.toLowerCase())
    ) {
      const retryMessageId = lastMessage.id;
      const retryGraphRunId = lastMessage.run.graphRunId;
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, from: "user", text, attachments: [] },
        { id: `b-${Date.now()}`, from: "bot", text: "Retrying reconciliation…" },
      ]);
      setDraft("");
      await handleRetry(retryMessageId, retryGraphRunId);
      return;
    }

    const userMessage = { id: `u-${Date.now()}`, from: "user", text, attachments };
    setMessages((prev) => [...prev, userMessage]);
    setDraft("");
    setAttachments([]);
    setSending(true);

    const formData = new FormData();
    formData.append("message", text);
    formData.append("state", JSON.stringify(chatState || {}));
    userMessage.attachments.forEach((a) => formData.append("attachments", a.file, a.name));

    try {
      const res = await api.post("/api/chat/message", formData);
      const { reply, state, run, insights } = res.data;
      setChatState(state);

      const botMessageId = `b-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: botMessageId,
          from: "bot",
          text: reply,
          run: run ? { graphRunId: run.graph_run_id, status: "running" } : null,
        },
      ]);
      if (run?.graph_run_id) pollRun(botMessageId, run.graph_run_id);
      // A text-driven "show me insights" resolved to a run backend-side (see
      // orchestrator.handle_message's INSIGHTS branch) — attach its PDF to
      // this same bot message rather than replacing the reply text.
      if (insights?.run_id) {
        await attachBlobToMessage(botMessageId, {
          method: "post",
          url: "/insights/pdf",
          data: { run_id: insights.run_id },
          filename: `insights_${insights.run_id}.pdf`,
          attachmentId: `insights-pdf-${insights.run_id}`,
        });
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `b-${Date.now()}`,
          from: "bot",
          text: err?.response?.data?.detail || "Something went wrong reaching the assistant.",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <>
      <button
        type="button"
        className={styles.launcher}
        onClick={() => setOpen(true)}
        aria-label="Open assistant"
        aria-expanded={open}
        aria-hidden={open}
        tabIndex={open ? -1 : 0}
      >
        <Bot size={28} strokeWidth={1.75} />
      </button>

      <div
        className={`${styles.backdrop}${open ? ` ${styles.backdropOpen}` : ""}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      <aside
        className={`${styles.panel}${open ? ` ${styles.panelOpen}` : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Assistant"
        aria-hidden={!open}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className={styles.head}>
          <span className={styles.headIcon}>
            <Bot size={18} strokeWidth={1.75} />
          </span>
          <div className={styles.headText}>
            <h3 className={styles.title}>Assistant</h3>
            <span className={styles.subtitle}>Always here to help</span>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={() => setOpen(false)}
            aria-label="Close assistant"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.body} ref={scrollRef}>
          {messages.map((m) => (
            <Message
              key={m.id}
              message={m}
              onResolve={handleResolve}
              onDownloadAttachment={handleDownloadAttachment}
            />
          ))}
        </div>

        {(lastMessage?.run?.status === "completed" ||
          (lastMessage?.run?.status === "failed" && lastMessage.run.resumable)) && (
          <FloatingSuggestions
            run={lastMessage.run}
            onViewInsights={() => handleViewInsights(lastMessage.run)}
            onRunNext={handleRunNext}
            onRetry={() => handleRetry(lastMessage.id, lastMessage.run.graphRunId)}
          />
        )}

        {attachments.length > 0 && (
          <div className={styles.attachmentTray}>
            {attachments.map((a) => (
              <AttachmentChip key={a.id} attachment={a} onRemove={removeAttachment} />
            ))}
          </div>
        )}

        <div className={styles.composer}>
          <div className={styles.inputRow}>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className={styles.hiddenFileInput}
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className={styles.attach}
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach files"
              title="Attach files"
            >
              <Plus size={18} />
            </button>
            <textarea
              className={styles.input}
              placeholder="Type a message, or drop / paste files…"
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
            />
            <button
              type="button"
              className={styles.send}
              onClick={sendMessage}
              disabled={sending || (!draft.trim() && attachments.length === 0)}
              aria-label="Send message"
            >
              <Send size={16} />
            </button>
          </div>
          <div className={styles.composerHint}>
            <span className={styles.composerHintLeft}>
              <Paperclip size={13} />
              Attach with +, drag, or paste
            </span>
            <span className={styles.composerHintRight}>Enter to send · Esc to close</span>
          </div>
        </div>

        {dragActive && (
          <div className={styles.dropOverlay} aria-hidden="true">
            <div className={styles.dropOverlayInner}>
              <Paperclip size={22} />
              <span>Drop files to attach</span>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}

export default AssistantBot;
