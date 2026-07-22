import type { Meta, StoryObj } from "@storybook/react";
import { Input, Textarea } from "./Input";

const meta: Meta<typeof Input> = {
  title: "Components/Input",
  component: Input,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Input>;

export const Default: Story = { args: { label: "SAP System ID", placeholder: "e.g. S4H" } };
export const WithHint: Story = { args: { label: "API Key", hint: "Generated from the gateway dashboard", placeholder: "bcone-sk-..." } };
export const WithError: Story = { args: { label: "Email", error: "Invalid email address", value: "notanemail", readOnly: true } };
export const Disabled: Story = { args: { label: "Client ID", disabled: true, value: "AUTO-GENERATED" } };

export const TextareaExample: StoryObj<typeof Textarea> = {
  render: () => (
    <Textarea
      label="SAP Requirement"
      placeholder="Describe the business requirement in plain language..."
      hint="Be as specific as possible for better AI output"
      rows={5}
    />
  ),
};
