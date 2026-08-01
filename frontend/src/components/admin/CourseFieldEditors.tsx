import { useRef, useState, type ReactNode } from "react";
import { D, mono } from "../../design/tokens";
import { Btn } from "../../design/atoms";

const cellStyle = { padding: "4px 6px", verticalAlign: "middle" as const };
const headerCellStyle = {
  padding: "6px 10px",
  fontWeight: 600,
  color: D.muted,
  textTransform: "uppercase" as const,
  fontSize: 10,
  letterSpacing: 0.4,
  textAlign: "left" as const,
};

const inputStyle = {
  width: "100%",
  boxSizing: "border-box" as const,
  background: D.bg,
  color: D.text,
  border: `1px solid ${D.border}`,
  borderRadius: 6,
  padding: "6px 8px",
  fontSize: 12,
};

function TableShell({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        border: `1px solid ${D.border}`,
        borderRadius: 8,
        overflow: "hidden",
        background: D.surface,
      }}
    >
      <table style={{ width: "100%", borderCollapse: "collapse" }}>{children}</table>
    </div>
  );
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Remove row"
      style={{
        background: "transparent",
        border: "none",
        color: D.red,
        cursor: "pointer",
        fontSize: 14,
        padding: "2px 6px",
        width: "auto",
      }}
    >
      ✕
    </button>
  );
}

function useRowIdCounter() {
  const counter = useRef(0);
  return () => {
    counter.current += 1;
    return `row-${counter.current}`;
  };
}

// --- Syllabus matrix -------------------------------------------------------

interface SyllabusRow {
  id: string;
  week: string;
  allowed: string;
  forbidden: string;
}

function parseSyllabusMatrix(raw: string, nextId: () => string): SyllabusRow[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return [];
    return Object.entries(parsed as Record<string, { allowed?: string; forbidden?: string }>)
      .sort(([a], [b]) => {
        const na = Number(a);
        const nb = Number(b);
        if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
        return a.localeCompare(b);
      })
      .map(([week, data]) => ({
        id: nextId(),
        week,
        allowed: data?.allowed ?? "",
        forbidden: data?.forbidden ?? "",
      }));
  } catch {
    return [];
  }
}

function serializeSyllabusMatrix(rows: SyllabusRow[]): string {
  const matrix: Record<string, { allowed: string; forbidden: string }> = {};
  for (const row of rows) {
    const week = row.week.trim();
    if (!week) continue;
    matrix[week] = { allowed: row.allowed, forbidden: row.forbidden };
  }
  return Object.keys(matrix).length === 0 ? "" : JSON.stringify(matrix);
}

export function SyllabusMatrixEditor({
  initialValue,
  onChange,
}: {
  initialValue: string;
  onChange: (value: string) => void;
}) {
  const nextId = useRowIdCounter();
  const [rows, setRows] = useState<SyllabusRow[]>(() => parseSyllabusMatrix(initialValue, nextId));

  const commit = (next: SyllabusRow[]) => {
    setRows(next);
    onChange(serializeSyllabusMatrix(next));
  };

  const updateRow = (id: string, patch: Partial<SyllabusRow>) => {
    commit(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const addRow = () => {
    const nextWeekNumber =
      rows.reduce((max, row) => {
        const n = Number(row.week);
        return Number.isFinite(n) && n > max ? n : max;
      }, 0) + 1;
    commit([...rows, { id: nextId(), week: String(nextWeekNumber), allowed: "", forbidden: "" }]);
  };

  const removeRow = (id: string) => commit(rows.filter((row) => row.id !== id));

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {rows.length > 0 && (
        <TableShell>
          <thead>
            <tr style={{ borderBottom: `1px solid ${D.border}` }}>
              <th style={{ ...headerCellStyle, width: 70 }}>Week</th>
              <th style={headerCellStyle}>Allowed</th>
              <th style={headerCellStyle}>Forbidden</th>
              <th style={{ ...headerCellStyle, width: 32 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ borderTop: `1px solid ${D.border}` }}>
                <td style={cellStyle}>
                  <input
                    value={row.week}
                    onChange={(e) => updateRow(row.id, { week: e.target.value })}
                    style={{ ...inputStyle, ...mono, fontWeight: 600 }}
                    placeholder="1"
                  />
                </td>
                <td style={cellStyle}>
                  <input
                    value={row.allowed}
                    onChange={(e) => updateRow(row.id, { allowed: e.target.value })}
                    style={inputStyle}
                    placeholder="loops, arrays"
                  />
                </td>
                <td style={cellStyle}>
                  <input
                    value={row.forbidden}
                    onChange={(e) => updateRow(row.id, { forbidden: e.target.value })}
                    style={inputStyle}
                    placeholder="pointers"
                  />
                </td>
                <td style={{ ...cellStyle, textAlign: "center" }}>
                  <RemoveButton onClick={() => removeRow(row.id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
      <div>
        <Btn small variant="ghost" onClick={addRow}>
          + Add week
        </Btn>
      </div>
    </div>
  );
}

// --- Launch configs ----------------------------------------------------------

interface LaunchConfigRow {
  id: string;
  launch_id: string;
  label: string;
  repo_url: string;
  default_branch: string;
  enabled: boolean;
  // Preserved but not directly editable in this table, so existing values on
  // courses that already set them aren't silently dropped on save.
  template_url: string;
  sort_order: number;
}

function parseLaunchConfigs(raw: string, nextId: () => string): LaunchConfigRow[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((config: Record<string, unknown>) => ({
      id: nextId(),
      launch_id: String(config.launch_id ?? ""),
      label: String(config.label ?? ""),
      repo_url: String(config.repo_url ?? ""),
      default_branch: String(config.default_branch ?? "main"),
      enabled: Boolean(config.enabled ?? false),
      template_url: String(config.template_url ?? ""),
      sort_order: Number(config.sort_order ?? 0),
    }));
  } catch {
    return [];
  }
}

function serializeLaunchConfigs(rows: LaunchConfigRow[]): string {
  // Rows still missing the required fields are in-progress drafts - leave
  // them out of the saved JSON rather than emit something the backend's
  // StudentLaunchConfig(launch_id: str, label: str) would reject.
  const complete = rows.filter((row) => row.launch_id.trim() && row.label.trim());
  return complete.length === 0
    ? ""
    : JSON.stringify(
        complete.map(({ id: _id, ...config }) => config)
      );
}

export function LaunchConfigsEditor({
  initialValue,
  onChange,
}: {
  initialValue: string;
  onChange: (value: string) => void;
}) {
  const nextId = useRowIdCounter();
  const [rows, setRows] = useState<LaunchConfigRow[]>(() => parseLaunchConfigs(initialValue, nextId));

  const commit = (next: LaunchConfigRow[]) => {
    setRows(next);
    onChange(serializeLaunchConfigs(next));
  };

  const updateRow = (id: string, patch: Partial<LaunchConfigRow>) => {
    commit(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  const addRow = () => {
    commit([
      ...rows,
      {
        id: nextId(),
        launch_id: "",
        label: "",
        repo_url: "",
        default_branch: "main",
        enabled: true,
        template_url: "",
        sort_order: rows.length,
      },
    ]);
  };

  const removeRow = (id: string) => commit(rows.filter((row) => row.id !== id));

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {rows.length > 0 && (
        <TableShell>
          <thead>
            <tr style={{ borderBottom: `1px solid ${D.border}` }}>
              <th style={headerCellStyle}>Label</th>
              <th style={headerCellStyle}>Launch ID</th>
              <th style={headerCellStyle}>Repo URL</th>
              <th style={{ ...headerCellStyle, width: 90 }}>Branch</th>
              <th style={{ ...headerCellStyle, width: 60 }}>Enabled</th>
              <th style={{ ...headerCellStyle, width: 32 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ borderTop: `1px solid ${D.border}` }}>
                <td style={cellStyle}>
                  <input
                    value={row.label}
                    onChange={(e) => updateRow(row.id, { label: e.target.value })}
                    style={inputStyle}
                    placeholder="Week 1"
                  />
                </td>
                <td style={cellStyle}>
                  <input
                    value={row.launch_id}
                    onChange={(e) => updateRow(row.id, { launch_id: e.target.value })}
                    style={{ ...inputStyle, ...mono }}
                    placeholder="week1"
                  />
                </td>
                <td style={cellStyle}>
                  <input
                    value={row.repo_url}
                    onChange={(e) => updateRow(row.id, { repo_url: e.target.value })}
                    style={{ ...inputStyle, ...mono }}
                    placeholder="https://github.com/..."
                  />
                </td>
                <td style={cellStyle}>
                  <input
                    value={row.default_branch}
                    onChange={(e) => updateRow(row.id, { default_branch: e.target.value })}
                    style={{ ...inputStyle, ...mono }}
                  />
                </td>
                <td style={{ ...cellStyle, textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={(e) => updateRow(row.id, { enabled: e.target.checked })}
                  />
                </td>
                <td style={{ ...cellStyle, textAlign: "center" }}>
                  <RemoveButton onClick={() => removeRow(row.id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
      <div>
        <Btn small variant="ghost" onClick={addRow}>
          + Add launch config
        </Btn>
      </div>
    </div>
  );
}

// --- Style guide -------------------------------------------------------------

interface StyleGuideRow {
  id: string;
  text: string;
}

function parseStyleGuide(raw: string, nextId: () => string): StyleGuideRow[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((text) => ({ id: nextId(), text }));
}

function serializeStyleGuide(rows: StyleGuideRow[]): string {
  return rows
    .map((row) => row.text.trim())
    .filter(Boolean)
    .join("\n");
}

export function StyleGuideEditor({
  initialValue,
  onChange,
}: {
  initialValue: string;
  onChange: (value: string) => void;
}) {
  const nextId = useRowIdCounter();
  const [rows, setRows] = useState<StyleGuideRow[]>(() => parseStyleGuide(initialValue, nextId));

  const commit = (next: StyleGuideRow[]) => {
    setRows(next);
    onChange(serializeStyleGuide(next));
  };

  const updateRow = (id: string, text: string) => {
    commit(rows.map((row) => (row.id === id ? { ...row, text } : row)));
  };

  const addRow = () => commit([...rows, { id: nextId(), text: "" }]);
  const removeRow = (id: string) => commit(rows.filter((row) => row.id !== id));

  return (
    <div style={{ display: "grid", gap: 6 }}>
      {rows.length > 0 && (
        <TableShell>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ borderTop: `1px solid ${D.border}` }}>
                <td style={{ ...cellStyle, width: 20, color: D.orange, textAlign: "center" }}>•</td>
                <td style={cellStyle}>
                  <input
                    value={row.text}
                    onChange={(e) => updateRow(row.id, e.target.value)}
                    style={inputStyle}
                    placeholder="Indentation: 4 spaces"
                  />
                </td>
                <td style={{ ...cellStyle, width: 32, textAlign: "center" }}>
                  <RemoveButton onClick={() => removeRow(row.id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
      <div>
        <Btn small variant="ghost" onClick={addRow}>
          + Add rule
        </Btn>
      </div>
    </div>
  );
}
