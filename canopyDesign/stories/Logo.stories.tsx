import type { Meta, StoryObj } from "@storybook/react";
import { BristleconeLogo } from "../src/assets/BristleconeLogo";

const meta: Meta<typeof BristleconeLogo> = {
  title: "Brand/Logo",
  component: BristleconeLogo,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof BristleconeLogo>;

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-8">
      <div className="p-8 bg-white flex flex-col gap-4">
        <p className="text-xs font-bold text-gray-400 uppercase">Light background</p>
        <BristleconeLogo size="sm" variant="dark" />
        <BristleconeLogo size="md" variant="dark" />
        <BristleconeLogo size="lg" variant="dark" />
      </div>
      <div className="p-8 bg-[#192123] flex flex-col gap-4">
        <p className="text-xs font-bold text-gray-500 uppercase">Dark background</p>
        <BristleconeLogo size="sm" variant="light" />
        <BristleconeLogo size="md" variant="light" />
        <BristleconeLogo size="lg" variant="light" />
      </div>
      <div className="p-8 bg-white flex gap-4 items-center">
        <p className="text-xs font-bold text-gray-400 uppercase">Mark only</p>
        <BristleconeLogo size="sm" variant="mark-only" />
        <BristleconeLogo size="md" variant="mark-only" />
        <BristleconeLogo size="lg" variant="mark-only" />
      </div>
    </div>
  ),
};
