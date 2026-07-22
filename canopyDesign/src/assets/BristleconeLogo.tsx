import * as React from "react";
import { cn } from "../lib/utils";

export interface BristleconeLogoProps {
  size?: "sm" | "md" | "lg";
  variant?: "dark" | "light" | "mark-only";
  className?: string;
}

const sizes = {
  sm: { width: 120, height: 20 },
  md: { width: 180, height: 30 },
  lg: { width: 240, height: 40 },
};

export const BristleconeLogo: React.FC<BristleconeLogoProps> = ({
  size = "md",
  variant = "dark",
  className,
}) => {
  const { width, height } = sizes[size];
  const textColor = variant === "light" ? "#FFFFFF" : "#333536";
  const fontSize = height * 0.45;
  const barWidth = height * 0.1;
  const textX = barWidth + height * 0.15;

  if (variant === "mark-only") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={height}
        height={height}
        viewBox={`0 0 ${height} ${height}`}
        fill="none"
        role="img"
        aria-label="Bristlecone"
        className={cn(className)}
      >
        <rect x="0" y={height * 0.3} width={barWidth} height={height * 0.4} rx={barWidth / 2} fill="#21A6BD" />
        <circle cx={height * 0.85} cy={height * 0.65} r={barWidth * 0.75} fill="#21A6BD" />
      </svg>
    );
  }

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      role="img"
      aria-label="Bristlecone"
      className={cn(className)}
    >
      {/* Accent bar */}
      <rect x="0" y={height * 0.3} width={barWidth} height={height * 0.4} rx={barWidth / 2} fill="#21A6BD" />
      {/* Wordmark */}
      <text
        x={textX}
        y={height * 0.72}
        fontFamily="'Arial Black', 'Helvetica Neue', sans-serif"
        fontWeight="900"
        fontSize={fontSize}
        fill={textColor}
        letterSpacing="-0.5"
      >
        BRISTLECONE
      </text>
      {/* Teal dot mark */}
      <circle cx={width - 6} cy={height * 0.68} r={barWidth * 0.75} fill="#21A6BD" />
    </svg>
  );
};
