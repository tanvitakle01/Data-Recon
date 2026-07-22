import type { Meta, StoryObj } from "@storybook/react";
import { Inbox } from "lucide-react";
import { EmptyState } from "./EmptyState";
import { Button } from "../Button";

const meta: Meta<typeof EmptyState> = {
  title: "Components/EmptyState",
  component: EmptyState,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof EmptyState>;

export const Default: Story = {
  args: {
    icon: <Inbox />,
    title: "No connections yet",
    description: "Add your first connection to get started.",
  },
};

export const WithAction: Story = {
  render: () => (
    <EmptyState
      icon={<Inbox />}
      title="No documents"
      description="Upload a file to begin indexing."
      action={<Button>Upload</Button>}
    />
  ),
};
