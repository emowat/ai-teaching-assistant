import { D, mono } from "../design/tokens";
import type { AppView } from "../types/navigation";

interface TopBarProps {
  view: AppView;
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

export function TopBar({ view, onNavigate, demoMode = false }: TopBarProps) {
  return (
    <div
      style={{
        height: 48,
        background: D.bg,
        borderBottom: `1px solid ${D.border}`,
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        justifyContent: "space-between",
        flexShrink: 0,
      }}
    >
      <button
        type="button"
        onClick={() => onNavigate("landing")}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: 0,
        }}
      >
        <span style={{ ...mono, fontSize: 15, fontWeight: 700, color: D.text }}>
          codingrabbit<span style={{ color: D.orange }}>.dev</span>
        </span>
        <span style={{ fontSize: 14 }}>🐇</span>
      </button>

      {demoMode && view !== "landing" && (
        <div style={{ display: "flex", gap: 5 }}>
          {(
            [
              { v: "admin" as const, label: "Admin" },
              { v: "professor" as const, label: "Professor" },
              { v: "student" as const, label: "Student" },
            ] as const
          ).map(({ v, label }) => (
            <button
              key={v}
              type="button"
              onClick={() => onNavigate(v)}
              style={{
                background: view === v ? D.orangeGlow : "transparent",
                border: `1px solid ${view === v ? D.orangeBorder : D.border}`,
                color: view === v ? D.orange : D.muted,
                borderRadius: 6,
                padding: "4px 11px",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: view === v ? 500 : 400,
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
