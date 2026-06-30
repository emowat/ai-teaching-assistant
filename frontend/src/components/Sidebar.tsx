import type { ReactNode } from "react";
import { D } from "../design/tokens";

export interface SidebarTab {
  key: string;
  icon: string;
  label: string;
  disabled?: boolean;
  title?: string;
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
        width: 224,
        borderRight: `1px solid ${D.border}`,
        background: "rgba(255, 253, 248, 0.88)",
        padding: "16px 12px",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        boxShadow: "inset -1px 0 0 rgba(15, 23, 42, 0.02)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {tabs.map((t) => {
          const isDisabled = Boolean(t.disabled);
          return (
          <button
            key={t.key}
            type="button"
            title={t.title}
            disabled={isDisabled}
            onClick={() => {
              if (!isDisabled) onTab(t.key);
            }}
            style={{
              background: active === t.key ? "#FFFFFF" : "transparent",
              border: `1px solid ${active === t.key ? D.orangeBorder : "transparent"}`,
              color: active === t.key ? D.orange : isDisabled ? D.dim : D.muted,
              borderRadius: 14,
              padding: "10px 12px",
              cursor: isDisabled ? "not-allowed" : "pointer",
              textAlign: "left",
              fontSize: 13,
              fontWeight: active === t.key ? 700 : 500,
              display: "flex",
              alignItems: "center",
              gap: 8,
              opacity: isDisabled ? 0.45 : 1,
              boxShadow: active === t.key ? "0 8px 18px rgba(249, 115, 22, 0.08)" : "none",
            }}
          >
            <span style={{ fontSize: 14 }}>{t.icon}</span>
            <span>{t.label}</span>
          </button>
          );
        })}
      </div>
      <div style={{ flex: 1 }} />
      {footer}
    </div>
  );
}
