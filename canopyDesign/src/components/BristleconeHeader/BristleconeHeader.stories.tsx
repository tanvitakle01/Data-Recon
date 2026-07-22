import type { Meta, StoryObj } from "@storybook/react";
import { BristleconeHeader } from "./BristleconeHeader";
import { Button } from "../Button/Button";

const meta: Meta<typeof BristleconeHeader> = {
  title: "Components/BristleconeHeader",
  component: BristleconeHeader,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj<typeof BristleconeHeader>;

const user = { name: "Sunil Pillai", email: "sunil@bristlecone.com", role: "AI Architect" };

export const WithUser: Story = {
  render: () => (
    <BristleconeHeader
      appName="Bristlecone LLM Gateway"
      user={user}
      onLogout={() => alert("Logout")}
      onSettings={() => alert("Settings")}
      actions={<Button variant="ghost" size="sm">Docs</Button>}
    />
  ),
};

export const NoUser: Story = {
  render: () => <BristleconeHeader appName="Bristlecone LLM Gateway" />,
};

export const WithLogo: Story = {
  render: () => (
    <BristleconeHeader
      appName="SAP Config Advisor"
      user={user}
      logo={
        <div className="w-8 h-8 rounded bg-[var(--bcone-teal)] flex items-center justify-center text-white text-xs font-black">
          BC
        </div>
      }
    />
  ),
};
