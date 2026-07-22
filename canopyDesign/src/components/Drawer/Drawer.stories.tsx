import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { Drawer } from "./Drawer";
import { Button } from "../Button";

const meta: Meta<typeof Drawer> = {
  title: "Components/Drawer",
  component: Drawer,
  tags: ["autodocs"],
  argTypes: {
    side: { control: "inline-radio", options: ["left", "right", "top", "bottom"] },
    size: { control: "inline-radio", options: ["sm", "md", "lg"] },
  },
};

export default meta;
type Story = StoryObj<typeof Drawer>;

export const Default: Story = {
  args: { side: "right", size: "md" },
  render: (args) => {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open drawer</Button>
        <Drawer
          {...args}
          open={open}
          onClose={() => setOpen(false)}
          title="Filters"
          footer={<Button onClick={() => setOpen(false)}>Apply</Button>}
        >
          <p className="text-sm text-[var(--bcone-gray)]">
            Drawer content goes here — filters, details, secondary actions.
          </p>
        </Drawer>
      </>
    );
  },
};
