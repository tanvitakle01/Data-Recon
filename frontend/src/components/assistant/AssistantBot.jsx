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
import { Bot, FileText, Paperclip, Plus, Send, X } from "lucide-react";
import api from "../../services/api";
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
  return (
    <div className={styles.attachmentChip}>
      {attachment.isImage ? (
        <img src={attachment.previewUrl} alt={attachment.name} className={styles.attachmentThumb} />
      ) : (
        <span className={styles.attachmentIcon}>
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
};

const STEP_LABELS = {
  select_source: "Selecting source system…",
  import_source: "Importing source data…",
  select_target: "Selecting target system…",
  import_target: "Importing target data…",
  identify_candidate_keys: "Identifying candidate keys…",
  extract_unique_keys: "Extracting unique values…",
  pair_values: "Pairing values across systems…",
  compile_and_run: "Compiling & running reconciliation…",
};

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

  if (run.status === "waiting_for_input" && run.interrupt) {
    return (
      <div className={styles.resolver}>
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
        </div>
      </div>
    );
  }

  if (run.status === "completed") {
    return <ResultBadges summary={run.result?.result_summary?.summary} />;
  }

  if (run.status === "failed") {
    if (run.resumable) {
      const bp = run.batch_progress;
      return (
        <p className={styles.runInterrupted}>
          {bp
            ? `Reconciliation was interrupted after completing batch ${bp.batch_index + 1} of ` +
              `${bp.batch_count} (${bp.batch_label}). It can continue from where it left off.`
            : "Reconciliation was interrupted. It can continue from where it left off."}
        </p>
      );
    }
    return <p className={styles.runError}>{run.error || "Something went wrong."}</p>;
  }

  return (
    <p className={styles.runStatusLine}>
      {STEP_LABELS[run.current_step] || STATUS_LABELS[run.status] || "Working…"}
    </p>
  );
}

function Message({ message, onResolve, onDownloadAttachment }) {
  const { from, text, attachments, run } = message;
  return (
    <div className={`${styles.message} ${from === "user" ? styles.messageUser : styles.messageBot}`}>
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
        View Insights
      </button>
      <button type="button" className={styles.suggestionPill} onClick={onRunNext}>
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

  // "View Insights" stays inside the chat — it fetches the same structured
  // Insights PDF the Insights page's "Download PDF" button produces and
  // posts it as a new bot message, rather than navigating away from the chat.
  async function handleViewInsights(run) {
    const runId = run?.result?.result_summary?.run_id || run?.result?.run_id;
    if (!runId) return;
    const botMessageId = `b-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: botMessageId, from: "bot", text: "Here's the insights report for this run." },
    ]);
    try {
      const res = await api.get(`/insights/${runId}/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botMessageId
            ? {
                ...m,
                attachments: [
                  {
                    id: `insights-pdf-${runId}`,
                    name: `insights_${runId}.pdf`,
                    isImage: false,
                    previewUrl: null,
                    downloadUrl: blobUrl,
                  },
                ],
              }
            : m
        )
      );
    } catch {
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
    try {
      const res = await api.get(`/api/recon/runs/${runId}/comparison.xlsx`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId
            ? {
                ...m,
                attachments: [
                  ...(m.attachments || []),
                  {
                    id: `xlsx-${runId}`,
                    name: `results_${runId}.xlsx`,
                    isImage: false,
                    previewUrl: null,
                    downloadUrl: blobUrl,
                  },
                ],
              }
            : m
        )
      );
    } catch {
      // The results workbook is a nice-to-have alongside the results — a
      // failure here shouldn't disrupt the already-posted reconciliation results.
    }
  }

  // Watches for any message's run just having flipped to "completed" and
  // fetches its results workbook exactly once (guarded by whether the
  // message already carries that attachment).
  useEffect(() => {
    messages.forEach((m) => {
      if (m.run?.status !== "completed") return;
      const runId = m.run?.result?.result_summary?.run_id || m.run?.result?.run_id;
      if (!runId) return;
      const alreadyAttached = (m.attachments || []).some((a) => a.id === `xlsx-${runId}`);
      if (!alreadyAttached) attachResultsExcel(m.id, runId);
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
      const { reply, state, run } = res.data;
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
