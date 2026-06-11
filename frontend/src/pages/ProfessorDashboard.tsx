import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Avatar, Btn, Card, ProgressBar, Stat, Tag } from "../design/atoms";
import { chartTooltipStyle, D, mono } from "../design/tokens";
import { Sidebar } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";

interface ProfessorDashboardProps {
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

// STUB — replace when GET /professor/sections/:id/students is available
const students = [
  { id: "s1", name: "Alice Chen", last: "2h ago", sessions: 23, hints: 8, progress: 85, stuck: false },
  { id: "s2", name: "Bob Martinez", last: "15m ago", sessions: 18, hints: 14, progress: 62, stuck: true },
  { id: "s3", name: "Carol Liu", last: "1d ago", sessions: 31, hints: 3, progress: 94, stuck: false },
  { id: "s4", name: "David Osei", last: "3h ago", sessions: 12, hints: 19, progress: 45, stuck: true },
  { id: "s5", name: "Emma Park", last: "30m ago", sessions: 27, hints: 6, progress: 78, stuck: false },
];

// STUB — replace when analytics API is available
const weekData = [
  { week: "W1", sessions: 4, hints: 1 },
  { week: "W2", sessions: 6, hints: 2 },
  { week: "W3", sessions: 6, hints: 2 },
  { week: "W4", sessions: 7, hints: 3 },
  { week: "W5", sessions: 6, hints: 3 },
];

// STUB — replace when GET /professor/sections/:id/materials is available
const materials = [
  { week: "Week 1: Pointers & References", docs: 3, released: true },
  { week: "Week 2: Arrays & Strings", docs: 2, released: true },
  { week: "Week 3: Classes & OOP", docs: 4, released: false },
  { week: "Week 4: Templates", docs: 0, released: false },
];

const profTabs = [
  { key: "overview", icon: "📋", label: "Overview" },
  { key: "materials", icon: "📚", label: "Materials" },
  { key: "students", icon: "👥", label: "Students" },
  { key: "analytics", icon: "📊", label: "Analytics" },
];

export function ProfessorDashboard({ onNavigate, demoMode = false }: ProfessorDashboardProps) {
  const [tab, setTab] = useState("overview");
  const [monitorId, setMonitorId] = useState<string | null>(null);

  const monitored = students.find((s) => s.id === monitorId);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: D.bg,
        color: D.text,
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <TopBar view="professor" onNavigate={onNavigate} demoMode={demoMode} />
      <div
        style={{
          padding: "9px 20px",
          borderBottom: `1px solid ${D.border}`,
          display: "flex",
          alignItems: "center",
          gap: 14,
          background: D.surface,
        }}
      >
        <span style={{ fontSize: 13, color: D.muted }}>Teaching:</span>
        <select
          style={{
            background: D.card,
            border: `1px solid ${D.border}`,
            color: D.text,
            borderRadius: 6,
            padding: "5px 10px",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          <option>CS101 — Intro to C++</option>
          <option>CS201 — Data Structures</option>
        </select>
        <div style={{ flex: 1 }} />
        <Tag color={D.green}>32 enrolled</Tag>
        <Tag color={D.red}>2 stuck now</Tag>
        <Tag color={D.muted}>STUB</Tag>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          tabs={profTabs}
          active={monitorId ? null : tab}
          onTab={(t) => {
            setTab(t);
            setMonitorId(null);
          }}
        />

        <div style={{ flex: 1, overflow: "auto", padding: 22 }}>
          {monitorId && monitored ? (
            <div>
              <button
                type="button"
                onClick={() => setMonitorId(null)}
                style={{
                  background: "none",
                  border: "none",
                  color: D.orange,
                  cursor: "pointer",
                  fontSize: 13,
                  marginBottom: 18,
                  padding: 0,
                }}
              >
                ← Back to students
              </button>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
                <Avatar name={monitored.name} size={38} stuck={monitored.stuck} />
                <div style={{ fontSize: 17, fontWeight: 600 }}>{monitored.name}</div>
                {monitored.stuck && <Tag color={D.red}>🔴 Stuck</Tag>}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, 1fr)",
                  gap: 12,
                  marginBottom: 18,
                }}
              >
                <Stat label="// total_sessions" value={monitored.sessions} sub="all time" />
                <Stat label="// hints_used" value={monitored.hints} sub="this course" color={D.yellow} />
                <Stat
                  label="// curriculum_done"
                  value={`${monitored.progress}%`}
                  sub="of Week 2"
                  color={D.green}
                />
              </div>
            </div>
          ) : tab === "overview" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                CS101 — overview <Tag color={D.muted}>STUB</Tag>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 12,
                  marginBottom: 18,
                }}
              >
                <Stat label="// enrolled" value="32" sub="students" />
                <Stat label="// avg_progress" value="71%" sub="curriculum" color={D.green} />
                <Stat label="// stuck_now" value="2" sub="need attention" color={D.red} />
                <Stat label="// sessions_week" value="89" sub="this week" color={D.blue} />
              </div>
            </div>
          ) : tab === "materials" ? (
            <div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 18,
                }}
              >
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  Course materials <Tag color={D.muted}>STUB</Tag>
                </div>
                <Btn small>+ Upload document</Btn>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {materials.map((m) => (
                  <Card key={m.week} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 3 }}>{m.week}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>
                        {m.docs} document{m.docs !== 1 ? "s" : ""} uploaded
                      </div>
                    </div>
                    <Tag color={m.released ? D.green : D.muted}>
                      {m.released ? "✓ Released" : "Unreleased"}
                    </Tag>
                    {!m.released && <Btn small>Release</Btn>}
                  </Card>
                ))}
              </div>
            </div>
          ) : tab === "students" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                Students — CS101 <Tag color={D.muted}>STUB</Tag>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {students.map((s) => (
                  <Card
                    key={s.id}
                    onClick={() => setMonitorId(s.id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      borderColor: s.stuck ? `${D.red}40` : D.border,
                      background: s.stuck ? `${D.red}06` : D.card,
                    }}
                  >
                    <Avatar name={s.name} stuck={s.stuck} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>Last active: {s.last}</div>
                    </div>
                    <ProgressBar pct={s.progress} />
                    {s.stuck && <Tag color={D.red}>🔴 Stuck</Tag>}
                    <span style={{ color: D.muted, fontSize: 16 }}>›</span>
                  </Card>
                ))}
              </div>
            </div>
          ) : tab === "analytics" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                Class analytics <Tag color={D.muted}>STUB</Tag>
              </div>
              <Card>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>
                  // avg_sessions_and_hints_per_week
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={weekData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
                    <XAxis dataKey="week" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                    <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                    <Tooltip {...chartTooltipStyle} />
                    <Bar dataKey="sessions" fill={D.orange} radius={[3, 3, 0, 0]} name="avg sessions" />
                    <Bar dataKey="hints" fill={D.yellow} radius={[3, 3, 0, 0]} name="avg hints" />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
