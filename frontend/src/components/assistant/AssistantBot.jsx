// App-wide assistant bot — a large floating launcher (bigger than Mapping
// Review's fab, and visible on every authenticated page since it's mounted
// once in AppLayout) that slides a chat panel out from the right, 45vw wide
// and full viewport height. Chat content is a placeholder for now: a single
// automated greeting plus a basic send loop, no backend wiring yet.
import { useEffect, useRef, useState } from "react";
import { Bot, Send, X } from "lucide-react";
import styles from "./assistantBot.module.css";

const GREETING = {
  id: "greeting",
  from: "bot",
  text: "Hello! I'm your Data Reconciliation assistant. Ask me anything about your reconciliation runs.",
};

function Message({ from, text }) {
  return (
    <div className={`${styles.message} ${from === "user" ? styles.messageUser : styles.messageBot}`}>
      {text}
    </div>
  );
}

function AssistantBot() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([GREETING]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef(null);

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

  function sendMessage() {
    const text = draft.trim();
    if (!text) return;
    const userMessage = { id: `u-${Date.now()}`, from: "user", text };
    setMessages((prev) => [...prev, userMessage]);
    setDraft("");

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
            <Message key={m.id} from={m.from} text={m.text} />
          ))}
        </div>

        <div className={styles.inputRow}>
          <textarea
            className={styles.input}
            placeholder="Type a message…"
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            type="button"
            className={styles.send}
            onClick={sendMessage}
            disabled={!draft.trim()}
            aria-label="Send message"
          >
            <Send size={16} />
          </button>
        </div>
      </aside>
    </>
  );
}

export default AssistantBot;
