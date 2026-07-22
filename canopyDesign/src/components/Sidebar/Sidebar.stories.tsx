import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { LayoutDashboard, Key, BarChart2, Terminal, Settings, BookOpen } from "lucide-react";
import { Sidebar } from "./Sidebar";

const meta: Meta<typeof Sidebar> = {
  title: "Components/Sidebar",
  component: Sidebar,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj<typeof Sidebar>;

const sections = [
  {
    title: "Gateway",
    items: [
      { label: "Dashboard", icon: <LayoutDashboard />, active: true },
      { label: "API Keys", icon: <Key />, badge: 4 },
      { label: "Analytics", icon: <BarChart2 /> },
      { label: "Playground", icon: <Terminal /> },
    ],
  },
  {
    title: "Demo Apps",
    items: [
      { label: "RFP Drafter", icon: <BookOpen /> },
      { label: "Config Advisor", icon: <BookOpen /> },
    ],
  },
  {
    items: [{ label: "Settings", icon: <Settings /> }],
  },
];

export const Expanded: Story = {
  render: () => <div className="h-screen"><Sidebar sections={sections} /></div>,
};

export const Collapsed: Story = {
  render: () => <div className="h-screen"><Sidebar sections={sections} collapsed /></div>,
};

export const Toggleable: Story = {
  render: () => {
    const [collapsed, setCollapsed] = useState(false);
    return (
      <div className="h-screen flex">
        <Sidebar sections={sections} collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <div className="flex-1 bg-gray-50 p-8">
          <p className="text-sm text-gray-500">Main content area</p>
        </div>
      </div>
    );
  },
};
