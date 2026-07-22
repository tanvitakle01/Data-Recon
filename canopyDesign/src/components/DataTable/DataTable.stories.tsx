import type { Meta, StoryObj } from "@storybook/react";
import { DataTable } from "./DataTable";
import { Badge } from "../Badge/Badge";

const meta: Meta<typeof DataTable> = {
  title: "Components/DataTable",
  component: DataTable,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof DataTable>;

const apiKeyData = [
  { id: 1, name: "Presales Demo", model: "llama3.1-8b", calls: 1420, spend: "$2.84", status: "active" },
  { id: 2, name: "RFP Drafter App", model: "qwen2.5-coder:7b", calls: 892, spend: "$1.78", status: "active" },
  { id: 3, name: "Test Key", model: "llama3.1-8b", calls: 12, spend: "$0.02", status: "revoked" },
];

export const APIKeyTable: Story = {
  render: () => (
    <DataTable
      data={apiKeyData}
      columns={[
        { key: "name", header: "Key Name", sortable: true },
        { key: "model", header: "Default Model", sortable: true },
        { key: "calls", header: "API Calls", sortable: true },
        { key: "spend", header: "Spend" },
        {
          key: "status",
          header: "Status",
          render: (v) => (
            <Badge variant={v === "active" ? "success" : "error"} dot>
              {String(v)}
            </Badge>
          ),
        },
      ]}
    />
  ),
};

export const Empty: Story = {
  render: () => (
    <DataTable
      data={[]}
      columns={[
        { key: "name" as never, header: "Name" },
        { key: "status" as never, header: "Status" },
      ]}
      emptyMessage="No API keys found. Create your first key to get started."
    />
  ),
};
