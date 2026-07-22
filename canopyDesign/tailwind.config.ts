import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";
import bristleconePreset from "./src/theme/tailwind.config";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}", "./stories/**/*.{ts,tsx,mdx}"],
  presets: [bristleconePreset as Config],
  plugins: [tailwindcssAnimate],
};

export default config;
