import type { ReactNode } from "react";
import { D } from "../design/tokens";

export interface SidebarTab {
  key: string;
  icon: string;
  label: string;
}

interface SidebarProps {
  tabs: SidebarTab[];
  active: string | null;
  onTab: (key: string) => void;
  footer?: ReactNode;
}

export function Sidebar({ tabs, active, onTab, footer }: SidebarProps) {
  return (
    <div
      style={{
        width: 208,
        borderRight: `1px solid ${D.border}`,
        background: D.surface,
        padding: "14px 10px",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => onTab(t.key)}
            style={{
              background: active === t.key ? D.orangeGlow : "transparent",
              border: `1px solid ${active === t.key ? D.orangeBorder : "transparent"}`,
              color: active === t.key ? D.orange : D.muted,
              borderRadius: 7,
              padding: "9px 11px",
              cursor: "pointer",
              textAlign: "left",
              fontSize: 13,
              fontWeight: active === t.key ? 500 : 400,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 14 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      {footer}
    </div>
  );
}
