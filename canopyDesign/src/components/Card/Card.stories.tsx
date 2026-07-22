import type { Meta, StoryObj } from "@storybook/react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "./Card";
import { Button } from "../Button/Button";

const meta: Meta<typeof Card> = {
  title: "Components/Card",
  component: Card,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Card>;

export const Default: Story = {
  render: () => (
    <Card className="w-80">
      <CardHeader>
        <CardTitle>SAP Config Advisor</CardTitle>
        <CardDescription>AI-powered IMG customizing guidance</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-[var(--bcone-charcoal)]">
          Ask any SAP configuration question and get instant expert guidance.
        </p>
      </CardContent>
      <CardFooter>
        <Button size="sm">Open App</Button>
      </CardFooter>
    </Card>
  ),
};

export const Simple: Story = {
  render: () => (
    <Card className="w-80">
      <p className="text-sm">A simple padded card with no header or footer.</p>
    </Card>
  ),
};
