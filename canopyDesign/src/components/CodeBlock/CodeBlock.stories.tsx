import type { Meta, StoryObj } from "@storybook/react";
import { CodeBlock } from "./CodeBlock";

const meta: Meta<typeof CodeBlock> = {
  title: "Components/CodeBlock",
  component: CodeBlock,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof CodeBlock>;

const pythonExample = `from openai import OpenAI

client = OpenAI(
    base_url="https://api.llm-serving.bristlecone.net/v1",
    api_key="bcone-sk-your-key-here"
)

response = client.chat.completions.create(
    model="llama3.1-8b",
    messages=[{"role": "user", "content": "Explain SAP Universal Journal"}]
)

print(response.choices[0].message.content)`;

const abapExample = `CLASS zcl_s4_readiness_check DEFINITION PUBLIC FINAL.
  PUBLIC SECTION.
    METHODS check_obsolete_fm
      IMPORTING iv_fm_name TYPE tfdir-funcname
      RETURNING VALUE(rv_obsolete) TYPE abap_bool.
ENDCLASS.`;

export const Python: Story = {
  args: { code: pythonExample, language: "python", filename: "example.py" },
};

export const ABAP: Story = {
  args: { code: abapExample, language: "abap", filename: "zcl_s4_readiness_check.abap", showLineNumbers: true },
};

export const WithLineNumbers: Story = {
  args: { code: pythonExample, language: "python", showLineNumbers: true },
};
