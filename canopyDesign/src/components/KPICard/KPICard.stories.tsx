import type { Meta, StoryObj } from "@storybook/react";
import { Activity, Key, Cpu, DollarSign } from "lucide-react";
import { KPICard } from "./KPICard";

const meta: Meta<typeof KPICard> = {
  title: "Components/KPICard",
  component: KPICard,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof KPICard>;

export const GatewayDashboard: Story = {
  render: () => (
    <div className="grid grid-cols-4 gap-4 bg-gray-50 p-6">
      <KPICard label="API Calls Today" value="12,847" delta={18} icon={<Activity className="h-5 w-5" />} />
      <KPICard label="Active Keys" value="24" delta={0} icon={<Key className="h-5 w-5" />} />
      <KPICard label="Avg Latency" value="1.2s" delta={-8} deltaLabel="improvement" icon={<Cpu className="h-5 w-5" />} />
      <KPICard label="Spend (MTD)" value="$48.60" delta={12} icon={<DollarSign className="h-5 w-5" />} />
    </div>
  ),
};

export const Single: Story = {
  args: { label: "Total Tokens", value: "4.2M", delta: 22, deltaLabel: "vs last week" },
};
