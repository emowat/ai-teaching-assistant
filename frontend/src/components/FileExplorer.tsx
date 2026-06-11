import { useRef, useState } from "react";
import { D, mono } from "../design/tokens";

interface FileExplorerProps {
  files: Record<string, string>;
  activeFile: string;
  onSelectFile: (name: string) => void;
  onAddFile: (name: string) => void;
  onDeleteFile: (name: string) => void;
  projectName?: string;
}

function fileIcon(name: string): string {
  if (name.endsWith(".cpp") || name.endsWith(".cc") || name.endsWith(".cxx")) return "C";
  if (name.endsWith(".h") || name.endsWith(".hpp")) return "H";
  if (name.endsWith(".txt")) return "T";
  return "F";
}

function iconColor(name: string): string {
  if (name.endsWith(".cpp") || name.endsWith(".cc") || name.endsWith(".cxx")) return D.blue;
  if (name.endsWith(".h") || name.endsWith(".hpp")) return D.purple;
  return D.muted;
}

export function FileExplorer({
  files,
  activeFile,
  onSelectFile,
  onAddFile,
  onDeleteFile,
  projectName = "workspace",
}: FileExplorerProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [hoveredFile, setHoveredFile] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const WIDTH_OPEN = 188;
  const WIDTH_COLLAPSED = 36;

  const startAdd = () => {
    setAdding(true);
    setNewName("");
    setTimeout(() => inputRef.current?.focus(), 30);
  };

  const commitAdd = () => {
    const trimmed = newName.trim();
    if (trimmed && !Object.prototype.hasOwnProperty.call(files, trimmed)) {
      onAddFile(trimmed);
    }
    setAdding(false);
    setNewName("");
  };

  const handleAddKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") commitAdd();
    if (e.key === "Escape") {
      setAdding(false);
      setNewName("");
    }
  };

  const requestDelete = (name: string) => {
    if (Object.keys(files).length <= 1) return;
    setConfirmDelete(name);
  };

  const confirmAndDelete = (name: string) => {
    onDeleteFile(name);
    setConfirmDelete(null);
  };

  return (
    <div
      style={{
        width: collapsed ? WIDTH_COLLAPSED : WIDTH_OPEN,
        minWidth: collapsed ? WIDTH_COLLAPSED : WIDTH_OPEN,
        borderRight: `1px solid ${D.border}`,
        background: "#141414",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        transition: "width 0.15s ease, min-width 0.15s ease",
        overflow: "hidden",
      }}
    >
      {/* Header row */}
      <div
        style={{
          height: 34,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: collapsed ? "0 8px" : "0 8px 0 10px",
          borderBottom: `1px solid ${D.border}`,
          flexShrink: 0,
        }}
      >
        {!collapsed && (
          <span
            style={{
              ...mono,
              fontSize: 10,
              color: D.muted,
              textTransform: "uppercase",
              letterSpacing: 0.8,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
              flex: 1,
            }}
          >
            {projectName}
          </span>
        )}

        <div style={{ display: "flex", gap: 2, marginLeft: collapsed ? 0 : 4 }}>
          {!collapsed && (
            <button
              type="button"
              title="New file"
              onClick={startAdd}
              style={iconBtnStyle}
            >
              +
            </button>
          )}
          <button
            type="button"
            title={collapsed ? "Expand explorer" : "Collapse explorer"}
            onClick={() => setCollapsed((c) => !c)}
            style={iconBtnStyle}
          >
            {collapsed ? "›" : "‹"}
          </button>
        </div>
      </div>

      {/* File list (hidden when collapsed) */}
      {!collapsed && (
        <div style={{ flex: 1, overflow: "auto", padding: "4px 0" }}>
          {Object.keys(files).map((name) => {
            const isActive = name === activeFile;
            const isHovered = hoveredFile === name;
            const isPendingDelete = confirmDelete === name;

            return (
              <div
                key={name}
                onMouseEnter={() => setHoveredFile(name)}
                onMouseLeave={() => {
                  setHoveredFile(null);
                  if (confirmDelete === name) setConfirmDelete(null);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 8px 4px 12px",
                  cursor: "pointer",
                  background: isActive
                    ? D.orangeGlow
                    : isHovered
                      ? "rgba(255,255,255,0.04)"
                      : "transparent",
                  borderLeft: `2px solid ${isActive ? D.orange : "transparent"}`,
                }}
                onClick={() => onSelectFile(name)}
              >
                <span
                  style={{
                    ...mono,
                    fontSize: 9,
                    fontWeight: 700,
                    color: iconColor(name),
                    width: 12,
                    flexShrink: 0,
                    textAlign: "center",
                  }}
                >
                  {fileIcon(name)}
                </span>
                <span
                  style={{
                    ...mono,
                    fontSize: 12,
                    color: isActive ? D.text : D.dim,
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {name}
                </span>

                {/* Delete button — show on hover, confirm on first click */}
                {isHovered && Object.keys(files).length > 1 && (
                  isPendingDelete ? (
                    <button
                      type="button"
                      title="Confirm delete"
                      onClick={(e) => {
                        e.stopPropagation();
                        confirmAndDelete(name);
                      }}
                      style={{ ...iconBtnStyle, color: D.red, fontSize: 10 }}
                    >
                      del
                    </button>
                  ) : (
                    <button
                      type="button"
                      title="Delete file"
                      onClick={(e) => {
                        e.stopPropagation();
                        requestDelete(name);
                      }}
                      style={{ ...iconBtnStyle, fontSize: 14 }}
                    >
                      ×
                    </button>
                  )
                )}
              </div>
            );
          })}

          {/* New file input */}
          {adding && (
            <div style={{ padding: "4px 8px 4px 12px" }}>
              <input
                ref={inputRef}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={handleAddKeyDown}
                onBlur={commitAdd}
                placeholder="filename.cpp"
                style={{
                  width: "100%",
                  background: D.card,
                  border: `1px solid ${D.orangeBorder}`,
                  color: D.text,
                  borderRadius: 4,
                  padding: "3px 6px",
                  fontSize: 12,
                  outline: "none",
                  ...mono,
                  boxSizing: "border-box",
                }}
              />
            </div>
          )}
        </div>
      )}

      {/* Collapsed: show file dots */}
      {collapsed && (
        <div style={{ flex: 1, overflow: "hidden", paddingTop: 6 }}>
          {Object.keys(files).map((name) => (
            <div
              key={name}
              title={name}
              onClick={() => {
                setCollapsed(false);
                onSelectFile(name);
              }}
              style={{
                height: 28,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                borderLeft: `2px solid ${name === activeFile ? D.orange : "transparent"}`,
              }}
            >
              <span
                style={{
                  ...mono,
                  fontSize: 9,
                  fontWeight: 700,
                  color: name === activeFile ? D.orange : iconColor(name),
                }}
              >
                {fileIcon(name)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const iconBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: D.muted,
  cursor: "pointer",
  padding: "2px 4px",
  fontSize: 16,
  lineHeight: 1,
  borderRadius: 3,
  flexShrink: 0,
};
