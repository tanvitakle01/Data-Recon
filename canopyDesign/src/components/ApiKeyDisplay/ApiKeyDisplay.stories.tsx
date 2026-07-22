import type { Meta, StoryObj } from "@storybook/react";
import { ApiKeyDisplay } from "./ApiKeyDisplay";

const meta: Meta<typeof ApiKeyDisplay> = {
  title: "Components/ApiKeyDisplay",
  component: ApiKeyDisplay,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof ApiKeyDisplay>;

export const Default: Story = {
  args: {
    apiKey: "bcone-sk-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
    label: "Your API Key",
  },
};

export const NoLabel: Story = {
  args: { apiKey: "bcone-sk-abcdef1234567890abcdef1234567890" },
};
