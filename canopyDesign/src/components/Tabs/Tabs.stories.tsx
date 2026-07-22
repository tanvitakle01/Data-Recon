import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { Tabs } from "./Tabs";

const meta: Meta<typeof Tabs> = {
  title: "Components/Tabs",
  component: Tabs,
  tags: ["autodocs"],
  argTypes: {
    variant: { control: "inline-radio", options: ["underline", "pills"] },
  },
};

export default meta;
type Story = StoryObj<typeof Tabs>;

const items = [
  { id: "overview", label: "Overview" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
];

export const Underline: Story = {
  args: { variant: "underline" },
  render: (args) => {
    const [value, setValue] = useState("overview");
    return <Tabs {...args} items={items} value={value} onChange={setValue} />;
  },
};

export const Pills: Story = {
  args: { variant: "pills" },
  render: (args) => {
    const [value, setValue] = useState("overview");
    return <Tabs {...args} items={items} value={value} onChange={setValue} />;
  },
};
