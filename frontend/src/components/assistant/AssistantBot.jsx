// App-wide assistant bot — a large floating launcher (bigger than Mapping
// Review's fab, and visible on every authenticated page since it's mounted
// once in AppLayout) that slides a chat panel out from the right, 45vw wide
// and full viewport height. Chat content is a placeholder for now: a single
// automated greeting plus a basic send loop, no backend wiring yet. The
// input row supports attaching files three ways — the "+" button (native
// file picker), dragging files anywhere onto the open panel, and pasting
// files from the clipboard — all three funnel into the same attachment list.
import { useEffect, useRef, useState } from "react";
import { Bot, FileText, Paperclip, Plus, Send, X } from "lucide-react";
import styles from "./assistantBot.module.css";

const GREETING = {
  id: "greeting",
  from: "bot",
  text: "Hello! I'm your Data Reconciliation assistant. Ask me anything about your reconciliation runs.",
};

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

function AttachmentChip({ attachment, onRemove }) {
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
        <span className={styles.attachmentSize}>{formatFileSize(attachment.size)}</span>
      </div>
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

function Message({ from, text, attachments }) {
  return (
    <div className={`${styles.message} ${from === "user" ? styles.messageUser : styles.messageBot}`}>
      {text && <div>{text}</div>}
      {attachments?.length > 0 && (
        <div className={styles.messageAttachments}>
          {attachments.map((a) => (
            <AttachmentChip key={a.id} attachment={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function AssistantBot() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([GREETING]);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const scrollRef = useRef(null);
  const fileInputRef = useRef(null);
  const dragDepthRef = useRef(0);

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

  // Revoke every outstanding object URL on unmount, since image previews are
  // created eagerly as files are attached.
  useEffect(() => {
    return () => {
      attachments.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  function sendMessage() {
    const text = draft.trim();
    if (!text && attachments.length === 0) return;
    const userMessage = { id: `u-${Date.now()}`, from: "user", text, attachments };
    setMessages((prev) => [...prev, userMessage]);
    setDraft("");
    setAttachments([]);

    // Placeholder automated reply — swap for a real backend call later.
    window.setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: `b-${Date.now()}`,
          from: "bot",
          text: "Thanks for your message — this assistant is still being wired up, so I can't act on requests yet.",
        },
      ]);
    }, 500);
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
            <Message key={m.id} from={m.from} text={m.text} attachments={m.attachments} />
          ))}
        </div>

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
            disabled={!draft.trim() && attachments.length === 0}
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
