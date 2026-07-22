import type { Meta, StoryObj } from "@storybook/react";
import { Badge } from "./Badge";

const meta: Meta<typeof Badge> = {
  title: "Components/Badge",
  component: Badge,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Badge>;

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <Badge variant="success" dot>Active</Badge>
      <Badge variant="warning" dot>Degraded</Badge>
      <Badge variant="error" dot>Error</Badge>
      <Badge variant="info">Info</Badge>
      <Badge variant="teal">Teal</Badge>
      <Badge variant="purple">Tag</Badge>
      <Badge variant="default">Default</Badge>
    </div>
  ),
};

export const SAPStatuses: Story = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <Badge variant="success">S/4HANA Ready</Badge>
      <Badge variant="warning">Requires Review</Badge>
      <Badge variant="error">ATC Violations</Badge>
      <Badge variant="info">In Progress</Badge>
      <Badge variant="purple">ABAP</Badge>
      <Badge variant="teal">Fiori</Badge>
    </div>
  ),
};
