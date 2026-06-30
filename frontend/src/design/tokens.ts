import type { CSSProperties } from "react";

export const D = {
  bg: "#FAF7F0",
  surface: "#FFFDF8",
  card: "#FFFFFF",
  border: "#E7DDCF",
  orange: "#F97316",
  orangeGlow: "rgba(249,115,22,0.10)",
  orangeBorder: "rgba(249,115,22,0.24)",
  text: "#1F2937",
  muted: "#6B7280",
  dim: "#94A3B8",
  green: "#16A34A",
  red: "#EF4444",
  yellow: "#D97706",
  blue: "#2563EB",
  purple: "#7C3AED",
} as const;

export const mono: CSSProperties = {
  fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
};

export const chartTooltipStyle = {
  contentStyle: {
    background: "#FFFFFF",
    border: "1px solid #E7DDCF",
    borderRadius: 12,
    fontSize: 12,
    color: "#1F2937",
    boxShadow: "0 12px 30px rgba(15, 23, 42, 0.08)",
  },
  labelStyle: { color: "#9CA3AF" },
};
