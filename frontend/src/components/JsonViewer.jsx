import { useEffect, useState } from "react";
import { createHighlighterCore } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";
import jsonLang from "shiki/langs/json.mjs";
import catppuccinMocha from "shiki/themes/catppuccin-mocha.mjs";
import { Copy, Check } from "lucide-react";
import { cn } from "@bristlecone/canopy";

// Fine-grained shiki: bundle ONLY the JSON grammar + one theme + the JS regex
// engine (no oniguruma wasm). shiki's default `codeToHtml` entry pulls in every
// grammar/theme (~10MB of chunks) — this keeps it to what we actually render.
// Singleton so the highlighter is created once and reused across instances.
let highlighterPromise;
function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighterCore({
      themes: [catppuccinMocha],
      langs: [jsonLang],
      engine: createJavaScriptRegexEngine(),
    });
  }
  return highlighterPromise;
}

/**
 * Syntax-highlighted code/JSON viewer — the app's bespoke replacement for the
 * old `<pre class="contract-json">`. Canopy's exported CodeBlock renders plain
 * (unhighlighted) text, so this uses shiki directly for real token coloring,
 * wrapped in a Canopy-styled dark card with a copy button. Used for contract
 * JSON and evidence strings.
 *
 * `value` may be an object (pretty-printed as JSON) or a raw string. The
 * Catppuccin Mocha theme matches Canopy CodeBlock's dark palette (#1e1e2e).
 */
export default function JsonViewer({
  value,
  language = "json",
  filename,
  className,
  maxHeight = 420,
}) {
  const code =
    typeof value === "string" ? value : JSON.stringify(value ?? null, null, 2);

  const [html, setHtml] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    // Only the json grammar is bundled; other languages render as plain text.
    if (language !== "json") {
      setHtml(null);
      return;
    }
    let alive = true;
    getHighlighter()
      .then((hl) => hl.codeToHtml(code, { lang: "json", theme: "catppuccin-mocha" }))
      .then((out) => {
        if (alive) setHtml(out);
      })
      .catch(() => {
        // Highlight failure — fall back to plain text.
        if (alive) setHtml(null);
      });
    return () => {
      alive = false;
    };
  }, [code, language]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={cn(
        "rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 overflow-hidden shadow-[var(--bcone-shadow-sm)]",
        className
      )}
    >
      {/* Header — mirrors Canopy CodeBlock's header bar. */}
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
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white transition-colors py-0.5 px-2 rounded hover:bg-white/10"
          aria-label="Copy"
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

      {/* Body — shiki output, or a plain fallback while it loads / on error. */}
      <div
        className="overflow-auto text-sm leading-relaxed json-viewer__body"
        style={{ maxHeight, background: "#1e1e2e" }}
      >
        {html ? (
          <div
            className="json-viewer__shiki"
            // shiki output is generated from our own trusted content.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <pre className="p-4 font-code text-[#cdd6f4] whitespace-pre">
            <code>{code}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
