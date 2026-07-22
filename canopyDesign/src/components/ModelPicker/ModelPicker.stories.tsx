import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { ModelPicker } from "./ModelPicker";
import type { Model } from "./ModelPicker";

const meta: Meta<typeof ModelPicker> = {
  title: "Components/ModelPicker",
  component: ModelPicker,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof ModelPicker>;

const models: Model[] = [
  { id: "llama3.1-8b", name: "Llama 3.1 8B", provider: "ollama", contextWindow: 128000, tags: ["fast", "local"] },
  { id: "qwen2.5-coder-7b", name: "Qwen 2.5 Coder 7B", provider: "ollama", contextWindow: 32000, tags: ["code"] },
  { id: "llama3.1-70b", name: "Llama 3.1 70B", provider: "vllm", contextWindow: 128000, tags: ["powerful"], available: false },
  { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", provider: "claude", contextWindow: 200000, tags: ["fallback"] },
];

export const Default: Story = {
  render: () => {
    const [model, setModel] = useState("llama3.1-8b");
    return <ModelPicker models={models} value={model} onChange={setModel} className="w-72" />;
  },
};
