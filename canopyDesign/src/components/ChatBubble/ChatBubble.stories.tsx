import type { Meta, StoryObj } from "@storybook/react";
import { ChatBubble } from "./ChatBubble";

const meta: Meta<typeof ChatBubble> = {
  title: "Components/ChatBubble",
  component: ChatBubble,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof ChatBubble>;

export const UserMessage: Story = {
  args: { role: "user", content: "What is the purpose of the Universal Journal in SAP S/4HANA?", timestamp: "10:42 AM" },
};

export const AssistantMessage: Story = {
  args: {
    role: "assistant",
    content: "The Universal Journal (table ACDOCA) is the single source of truth in SAP S/4HANA Finance. It consolidates all accounting documents — FI, CO, Asset Accounting, and Material Ledger — into a single line-item table, eliminating the reconciliation effort required in classic ERP.",
    model: "llama3.1-8b",
    timestamp: "10:42 AM",
  },
};

export const Streaming: Story = {
  args: {
    role: "assistant",
    content: "The Universal Journal is a central concept in S/4HANA",
    isStreaming: true,
    model: "llama3.1-8b",
  },
};

export const Conversation: Story = {
  render: () => (
    <div className="flex flex-col gap-4 p-6 bg-gray-50 max-w-2xl">
      <ChatBubble
        role="user"
        content="How do I configure a new profit center in SAP S/4HANA?"
        timestamp="10:41 AM"
      />
      <ChatBubble
        role="assistant"
        content={`To configure a profit center in S/4HANA:\n\n1. Go to transaction **KE51** (Create Profit Center)\n2. Enter Controlling Area and Profit Center ID\n3. Set the validity period and assign to a Standard Hierarchy node\n4. Activate via **KCH5N**\n\nAlternatively, use the Fiori app "Manage Profit Centers" for a guided experience.`}
        model="llama3.1-8b"
        timestamp="10:41 AM"
      />
      <ChatBubble
        role="user"
        content="What's the difference between profit center and cost center?"
        timestamp="10:43 AM"
      />
    </div>
  ),
};
