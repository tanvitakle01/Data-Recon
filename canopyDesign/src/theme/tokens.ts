export const colors = {
  // Primary palette (80% of UI)
  teal: "#21A6BD",
  green: "#4BC984",
  charcoal: "#333536",
  gray: "#7F7F7F",
  lightGreen: "#67C381",
  blue: "#44AAC0",
  cyan: "#45AFC2",
  black: "#192123",
  white: "#FFFFFF",

  // Expanded palette (max 20% of UI)
  orange: "#E05E00",
  purple: "#68125E",
  yellow: "#FCDE0F",
  red: "#BF0D3F",
} as const;

export const spacing = {
  1: "4px",
  2: "8px",
  4: "16px",
  6: "24px",
  8: "32px",
  12: "48px",
  16: "64px",
} as const;

export const borderRadius = {
  sm: "4px",
  md: "8px",
  lg: "12px",
  pill: "9999px",
} as const;

export const shadows = {
  sm: "0 1px 3px rgba(25, 33, 35, 0.08), 0 1px 2px rgba(25, 33, 35, 0.04)",
  md: "0 4px 6px rgba(25, 33, 35, 0.07), 0 2px 4px rgba(25, 33, 35, 0.06)",
  lg: "0 10px 15px rgba(25, 33, 35, 0.10), 0 4px 6px rgba(25, 33, 35, 0.05)",
} as const;

export const typography = {
  fontDisplay: '"Arial Black", "Helvetica Neue", sans-serif',
  fontBody: 'Arial, "Helvetica Neue", sans-serif',
  fontCode: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
  weightNormal: 400,
  weightBold: 700,
  weightBlack: 900,
} as const;
