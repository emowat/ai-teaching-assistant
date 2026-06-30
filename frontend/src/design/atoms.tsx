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
        background: `${color}12`,
        color,
        border: `1px solid ${color}24`,
        borderRadius: 999,
        padding: "4px 10px",
        fontSize: 11,
        fontWeight: 700,
        ...mono,
        letterSpacing: 0.4,
        whiteSpace: "nowrap",
        boxShadow: "0 6px 16px rgba(15, 23, 42, 0.04)",
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
    primary: {
      background: `linear-gradient(180deg, ${D.orange} 0%, #ea580c 100%)`,
      color: "#fff",
      border: "none",
      boxShadow: "0 10px 20px rgba(249, 115, 22, 0.22)",
    },
    ghost: {
      background: "#FFFFFF",
      color: D.text,
      border: `1px solid ${D.border}`,
      boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
    },
    danger: {
      background: `${D.red}10`,
      color: D.red,
      border: `1px solid ${D.red}24`,
    },
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...map[variant],
        borderRadius: 999,
        padding: pad,
        fontSize: fs,
        fontWeight: 700,
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
        borderRadius: 20,
        padding: "18px 20px",
        boxShadow: "0 14px 36px rgba(15, 23, 42, 0.06)",
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
          fontSize: 28,
          fontWeight: 700,
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
        background: stuck ? `${D.red}10` : `${color}12`,
        border: `1px solid ${stuck ? `${D.red}32` : `${color}24`}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.38,
        fontWeight: 700,
        color: stuck ? D.red : color,
        boxShadow: "0 8px 16px rgba(15, 23, 42, 0.05)",
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
          height: 6,
          background: D.border,
          borderRadius: 999,
          overflow: "hidden",
          width: 90,
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: bg,
            borderRadius: 999,
          }}
        />
      </div>
    </div>
  );
}
