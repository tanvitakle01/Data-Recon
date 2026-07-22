import * as React from "react";
import { User, Bot, Copy, Check } from "lucide-react";
import { cn } from "../../lib/utils";

export interface ChatBubbleProps {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
  model?: string;
  isStreaming?: boolean;
  className?: string;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({
  role,
  content,
  timestamp,
  model,
  isStreaming = false,
  className,
}) => {
  const [copied, setCopied] = React.useState(false);
  const isUser = role === "user";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={cn(
        "flex gap-3 group",
        isUser ? "flex-row-reverse" : "flex-row",
        className
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center",
          isUser
            ? "bg-[var(--bcone-teal)] text-white"
            : "bg-[var(--bcone-charcoal)] text-white"
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Bubble */}
      <div className={cn("flex flex-col gap-1 max-w-[75%]", isUser && "items-end")}>
        {(model || timestamp) && (
          <div className={cn("flex items-center gap-2 text-xs text-[var(--bcone-gray)]", isUser && "flex-row-reverse")}>
            {model && <span className="font-bold">{model}</span>}
            {timestamp && <span>{timestamp}</span>}
          </div>
        )}

        <div
          className={cn(
            "relative rounded-[var(--bcone-radius-md)] px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-[var(--bcone-teal)] text-white rounded-tr-[var(--bcone-radius-sm)]"
              : "bg-white border border-[var(--bcone-gray)]/20 text-[var(--bcone-charcoal)] shadow-[var(--bcone-shadow-sm)] rounded-tl-[var(--bcone-radius-sm)]"
          )}
        >
          <p className="whitespace-pre-wrap">{content}</p>
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 ml-0.5 bg-current opacity-70 animate-pulse" />
          )}

          {/* Copy button — visible on hover for assistant messages */}
          {!isUser && (
            <button
              onClick={handleCopy}
              className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-[var(--bcone-gray)]/10"
              aria-label="Copy message"
            >
              {copied
                ? <Check className="h-3.5 w-3.5 text-[var(--bcone-green)]" />
                : <Copy className="h-3.5 w-3.5 text-[var(--bcone-gray)]" />
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
