import * as React from "react";
import { Copy, Check } from "lucide-react";
import { cn } from "../../lib/utils";

export interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  showLineNumbers?: boolean;
  className?: string;
}

export const CodeBlock: React.FC<CodeBlockProps> = ({
  code,
  language = "text",
  filename,
  showLineNumbers = false,
  className,
}) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lines = code.split("\n");

  return (
    <div
      className={cn(
        "rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 overflow-hidden shadow-[var(--bcone-shadow-sm)]",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between bg-[var(--bcone-charcoal)] px-4 py-2">
        <div className="flex items-center gap-3">
          {filename && (
            <span className="text-xs text-white/70 font-code">{filename}</span>
          )}
          {language && (
            <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--bcone-cyan)] bg-white/10 px-2 py-0.5 rounded-sm">
              {language}
            </span>
          )}
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white transition-colors py-0.5 px-2 rounded hover:bg-white/10"
          aria-label="Copy code"
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-[var(--bcone-green)]" />
              <span className="text-[var(--bcone-green)]">Copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code */}
      <div className="bg-[#1e1e2e] overflow-x-auto">
        <pre className="p-4 text-sm leading-relaxed">
          <code
            className="font-code text-[#cdd6f4]"
            style={{ fontFamily: "var(--bcone-font-code)" }}
          >
            {showLineNumbers
              ? lines.map((line, i) => (
                  <span key={i} className="flex">
                    <span className="select-none w-8 text-right mr-4 text-[#585b70] text-xs">
                      {i + 1}
                    </span>
                    <span>{line}</span>
                  </span>
                ))
              : code}
          </code>
        </pre>
      </div>
    </div>
  );
};
