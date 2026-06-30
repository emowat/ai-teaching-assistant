import { getViewLabel } from "../auth/roleAccess";
import { D, mono } from "../design/tokens";
import type { AppView } from "../types/navigation";

interface TopBarProps {
  view: AppView;
  onNavigate: (view: AppView) => void;
  allowedViews?: AppView[];
  onSignOut?: () => void;
}

export function TopBar({
  view,
  onNavigate,
  allowedViews = [],
  onSignOut,
}: TopBarProps) {
  const showSwitcher = allowedViews.length > 1 && view !== "landing";

  return (
    <div
      style={{
        height: 48,
        background: "rgba(255, 253, 248, 0.84)",
        borderBottom: `1px solid ${D.border}`,
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        justifyContent: "space-between",
        flexShrink: 0,
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        boxShadow: "0 8px 24px rgba(15, 23, 42, 0.04)",
        position: "sticky",
        top: 0,
        zIndex: 20,
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
        <span style={{ ...mono, fontSize: 15, fontWeight: 800, color: D.text }}>
          codingrabbit<span style={{ color: D.orange }}>.dev</span>
        </span>
        <span style={{ fontSize: 14 }}>🐇</span>
      </button>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {showSwitcher && (
          <div style={{ display: "flex", gap: 5 }}>
            {allowedViews.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => onNavigate(v)}
                style={{
                  background: view === v ? D.orangeGlow : "#FFFFFF",
                  border: `1px solid ${view === v ? D.orangeBorder : D.border}`,
                  color: view === v ? D.orange : D.muted,
                  borderRadius: 999,
                  padding: "5px 12px",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: view === v ? 700 : 500,
                  boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
                }}
              >
                {getViewLabel(v)}
              </button>
            ))}
          </div>
        )}
        {onSignOut && (
          <button
            type="button"
            onClick={onSignOut}
            style={{
              background: "#FFFFFF",
              border: `1px solid ${D.border}`,
              color: D.text,
              borderRadius: 999,
              padding: "5px 12px",
              cursor: "pointer",
              fontSize: 12,
              boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
            }}
          >
            Sign out
          </button>
        )}
      </div>
    </div>
  );
}
