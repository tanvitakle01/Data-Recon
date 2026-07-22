import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, Cpu, Check } from "lucide-react";
import { cn } from "../../lib/utils";

export interface Model {
  id: string;
  name: string;
  provider: "ollama" | "vllm" | "claude" | "openai" | "azure";
  contextWindow?: number;
  tags?: string[];
  available?: boolean;
}

export interface ModelPickerProps {
  models: Model[];
  value: string;
  onChange: (modelId: string) => void;
  disabled?: boolean;
  className?: string;
}

const providerColors: Record<Model["provider"], string> = {
  ollama: "var(--bcone-teal)",
  vllm: "var(--bcone-blue)",
  claude: "var(--bcone-purple)",
  openai: "var(--bcone-green)",
  azure: "var(--bcone-blue)",
};

export const ModelPicker: React.FC<ModelPickerProps> = ({
  models,
  value,
  onChange,
  disabled = false,
  className,
}) => {
  const selected = models.find((m) => m.id === value);

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          disabled={disabled}
          className={cn(
            "flex items-center gap-2 h-10 px-3 rounded-[var(--bcone-radius-sm)] border border-[var(--bcone-gray)]/40 bg-white text-sm text-[var(--bcone-charcoal)] hover:border-[var(--bcone-teal)] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--bcone-teal)] disabled:opacity-50 disabled:cursor-not-allowed",
            className
          )}
        >
          <Cpu className="h-4 w-4 text-[var(--bcone-teal)]" />
          <span className="flex-1 text-left font-bold">
            {selected?.name ?? value ?? "Select model..."}
          </span>
          <ChevronDown className="h-4 w-4 text-[var(--bcone-gray)]" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 min-w-[260px] rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 bg-white shadow-[var(--bcone-shadow-lg)] p-1"
          sideOffset={4}
          align="start"
        >
          {models.map((model) => (
            <DropdownMenu.Item
              key={model.id}
              onSelect={() => onChange(model.id)}
              disabled={model.available === false}
              className={cn(
                "flex items-start gap-3 rounded-[var(--bcone-radius-sm)] px-3 py-2.5 text-sm cursor-pointer outline-none",
                "hover:bg-[var(--bcone-teal)]/8 focus:bg-[var(--bcone-teal)]/8",
                "data-[disabled]:opacity-40 data-[disabled]:cursor-not-allowed"
              )}
            >
              <span
                className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full"
                style={{ backgroundColor: providerColors[model.provider] }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-bold text-[var(--bcone-charcoal)]">{model.name}</span>
                  {value === model.id && <Check className="h-3.5 w-3.5 text-[var(--bcone-teal)]" />}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] font-bold uppercase text-[var(--bcone-gray)]">{model.provider}</span>
                  {model.contextWindow && (
                    <span className="text-[10px] text-[var(--bcone-gray)]">
                      {(model.contextWindow / 1000).toFixed(0)}K ctx
                    </span>
                  )}
                  {model.tags?.map((tag) => (
                    <span key={tag} className="text-[10px] bg-[var(--bcone-gray)]/10 rounded px-1">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
};
