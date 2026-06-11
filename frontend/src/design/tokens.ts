import type { CSSProperties } from "react";

export const D = {
  bg: "#080808",
  surface: "#101010",
  card: "#181818",
  border: "#242424",
  orange: "#E8531C",
  orangeGlow: "rgba(232,83,28,0.09)",
  orangeBorder: "rgba(232,83,28,0.28)",
  text: "#EFEFEF",
  muted: "#6B7280",
  dim: "#9CA3AF",
  green: "#34D399",
  red: "#F87171",
  yellow: "#FBBF24",
  blue: "#60A5FA",
  purple: "#A78BFA",
} as const;

export const mono: CSSProperties = {
  fontFamily: "'Courier New', Courier, monospace",
};

export const chartTooltipStyle = {
  contentStyle: {
    background: "#181818",
    border: "1px solid #242424",
    borderRadius: 6,
    fontSize: 12,
    color: "#EFEFEF",
  },
  labelStyle: { color: "#9CA3AF" },
};
