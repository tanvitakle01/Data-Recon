import * as React from "react";
import { Eye, EyeOff, Copy, Check } from "lucide-react";
import { cn } from "../../lib/utils";

export interface ApiKeyDisplayProps {
  apiKey: string;
  label?: string;
  className?: string;
}

export const ApiKeyDisplay: React.FC<ApiKeyDisplayProps> = ({
  apiKey,
  label = "API Key",
  className,
}) => {
  const [revealed, setRevealed] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  const masked = apiKey.slice(0, 8) + "•".repeat(Math.max(0, apiKey.length - 12)) + apiKey.slice(-4);
  const display = revealed ? apiKey : masked;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {label && (
        <label className="text-sm font-bold text-[var(--bcone-charcoal)]">{label}</label>
      )}
      <div className="flex items-center gap-0 rounded-[var(--bcone-radius-sm)] border border-[var(--bcone-gray)]/40 bg-white overflow-hidden">
        <code
          className="flex-1 px-3 py-2 text-sm font-code text-[var(--bcone-charcoal)] truncate select-all"
          style={{ fontFamily: "var(--bcone-font-code)" }}
        >
          {display}
        </code>

        <div className="flex border-l border-[var(--bcone-gray)]/20">
          <button
            onClick={() => setRevealed((r) => !r)}
            className="px-3 py-2 text-[var(--bcone-gray)] hover:text-[var(--bcone-teal)] hover:bg-[var(--bcone-teal)]/5 transition-colors"
            aria-label={revealed ? "Hide key" : "Reveal key"}
          >
            {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>

          <button
            onClick={handleCopy}
            className="px-3 py-2 text-[var(--bcone-gray)] hover:text-[var(--bcone-teal)] hover:bg-[var(--bcone-teal)]/5 transition-colors border-l border-[var(--bcone-gray)]/20"
            aria-label="Copy key"
          >
            {copied
              ? <Check className="h-4 w-4 text-[var(--bcone-green)]" />
              : <Copy className="h-4 w-4" />
            }
          </button>
        </div>
      </div>
      <p className="text-xs text-[var(--bcone-gray)]">
        Keep this key secret. It cannot be recovered — regenerate if lost.
      </p>
    </div>
  );
};
