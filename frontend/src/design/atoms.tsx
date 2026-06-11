import type { CSSProperties, ReactNode } from "react";
import { D, mono } from "./tokens";

interface TagProps {
  children: ReactNode;
  color?: string;
}

export function Tag({ children, color = D.orange }: TagProps) {
  return (
    <span
      style={{
        background: `${color}18`,
        color,
        border: `1px solid ${color}30`,
        borderRadius: 4,
        padding: "2px 7px",
        fontSize: 11,
        fontWeight: 500,
        ...mono,
        letterSpacing: 0.3,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

type BtnVariant = "primary" | "ghost" | "danger";

interface BtnProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: BtnVariant;
  small?: boolean;
  disabled?: boolean;
  style?: CSSProperties;
}

export function Btn({
  children,
  onClick,
  variant = "primary",
  small,
  disabled,
  style: sx = {},
}: BtnProps) {
  const pad = small ? "5px 11px" : "8px 18px";
  const fs = small ? 12 : 13;
  const map: Record<BtnVariant, CSSProperties> = {
    primary: { background: D.orange, color: "#fff", border: "none" },
    ghost: {
      background: "transparent",
      color: D.muted,
      border: `1px solid ${D.border}`,
    },
    danger: {
      background: `${D.red}18`,
      color: D.red,
      border: `1px solid ${D.red}30`,
    },
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...map[variant],
        borderRadius: 6,
        padding: pad,
        fontSize: fs,
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontFamily: "inherit",
        ...sx,
      }}
    >
      {children}
    </button>
  );
}

interface CardProps {
  children: ReactNode;
  style?: CSSProperties;
  onClick?: () => void;
}

export function Card({ children, style: sx = {}, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      style={{
        background: D.card,
        border: `1px solid ${D.border}`,
        borderRadius: 10,
        padding: "16px 18px",
        cursor: onClick ? "pointer" : undefined,
        ...sx,
      }}
    >
      {children}
    </div>
  );
}

interface StatProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}

export function Stat({ label, value, sub, color = D.orange }: StatProps) {
  return (
    <Card>
      <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 6 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 26,
          fontWeight: 600,
          color,
          lineHeight: 1.1,
          marginBottom: 4,
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: D.muted }}>{sub}</div>}
    </Card>
  );
}

interface AvatarProps {
  name: string;
  color?: string;
  size?: number;
  stuck?: boolean;
}

export function Avatar({ name, color = D.orange, size = 34, stuck }: AvatarProps) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        flexShrink: 0,
        background: stuck ? `${D.red}18` : D.orangeGlow,
        border: `1px solid ${stuck ? `${D.red}50` : D.orangeBorder}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.38,
        fontWeight: 600,
        color: stuck ? D.red : color,
      }}
    >
      {name[0]}
    </div>
  );
}

interface ProgressBarProps {
  pct: number;
}

export function ProgressBar({ pct }: ProgressBarProps) {
  const bg = pct > 75 ? D.green : pct > 50 ? D.orange : D.red;
  return (
    <div>
      <div style={{ fontSize: 10, color: D.muted, marginBottom: 3 }}>
        Progress {pct}%
      </div>
      <div
        style={{
          height: 3,
          background: D.border,
          borderRadius: 2,
          overflow: "hidden",
          width: 90,
        }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: bg }} />
      </div>
    </div>
  );
}
