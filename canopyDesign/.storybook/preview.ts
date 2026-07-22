import type { Preview } from "@storybook/react";
import "../src/theme/globals.css";
import "./storybook.css";

const preview: Preview = {
  parameters: {
    backgrounds: {
      default: "light",
      values: [
        { name: "light", value: "#FFFFFF" },
        { name: "surface", value: "#F8F8F8" },
        { name: "dark", value: "#192123" },
      ],
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    layout: "centered",
  },
};

export default preview;
