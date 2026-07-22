import type { Config } from "tailwindcss";
import { colors, spacing, borderRadius, shadows, typography } from "./tokens";

const bristleconePreset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        bcone: {
          teal: colors.teal,
          green: colors.green,
          charcoal: colors.charcoal,
          gray: colors.gray,
          "light-green": colors.lightGreen,
          blue: colors.blue,
          cyan: colors.cyan,
          black: colors.black,
          white: colors.white,
          orange: colors.orange,
          purple: colors.purple,
          yellow: colors.yellow,
          red: colors.red,
        },
      },
      spacing: {
        "bcone-1": spacing[1],
        "bcone-2": spacing[2],
        "bcone-4": spacing[4],
        "bcone-6": spacing[6],
        "bcone-8": spacing[8],
        "bcone-12": spacing[12],
        "bcone-16": spacing[16],
      },
      borderRadius: {
        "bcone-sm": borderRadius.sm,
        "bcone-md": borderRadius.md,
        "bcone-lg": borderRadius.lg,
        "bcone-pill": borderRadius.pill,
      },
      boxShadow: {
        "bcone-sm": shadows.sm,
        "bcone-md": shadows.md,
        "bcone-lg": shadows.lg,
      },
      fontFamily: {
        display: typography.fontDisplay,
        body: typography.fontBody,
        code: typography.fontCode,
      },
      fontWeight: {
        normal: String(typography.weightNormal),
        bold: String(typography.weightBold),
        black: String(typography.weightBlack),
      },
    },
  },
};

export default bristleconePreset;
