import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Avatar, Btn, Card, Stat, Tag } from "../design/atoms";
import { chartTooltipStyle, D, mono } from "../design/tokens";
import { Sidebar } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";

interface AdminDashboardProps {
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

// STUB — replace when analytics API is available
const sessionData = [
  { day: "Mon", sessions: 142, resolved: 104 },
  { day: "Tue", sessions: 189, resolved: 137 },
  { day: "Wed", sessions: 211, resolved: 150 },
  { day: "Thu", sessions: 167, resolved: 123 },
  { day: "Fri", sessions: 98, resolved: 69 },
  { day: "Sat", sessions: 43, resolved: 32 },
  { day: "Sun", sessions: 57, resolved: 42 },
];

// STUB — replace when model config API is available
const modelShare = [
  { name: "Sonnet", value: 78, color: D.orange },
  { name: "Haiku", value: 15, color: D.blue },
  { name: "Opus", value: 7, color: D.green },
];

// STUB — replace when GET /admin/models is available
const models = [
  { name: "claude-sonnet-4-20250514", active: true, tier: "Balanced", speed: "Fast", note: "Recommended" },
  { name: "claude-opus-4-20250514", active: false, tier: "Powerful", speed: "Slower", note: "High cost" },
  { name: "claude-haiku-4-5", active: false, tier: "Lightweight", speed: "Fastest", note: "Budget" },
];

// STUB — replace when GET /admin/users is available
const professors = [
  { name: "Dr. Rivera", email: "crivera@university.edu", courses: 3, students: 87, status: "active" },
  { name: "Prof. Kim", email: "jkim@university.edu", courses: 2, students: 54, status: "active" },
  { name: "Dr. Patel", email: "rpatel@university.edu", courses: 1, students: 30, status: "invited" },
];

// STUB — replace when GET /admin/courses is available
const courses = [
  { code: "CS101", name: "Intro to C++", prof: "Dr. Rivera", students: 32, status: "active" },
  { code: "CS201", name: "Data Structures", prof: "Prof. Kim", students: 28, status: "active" },
  { code: "CS301", name: "Algorithms", prof: "Dr. Rivera", students: 27, status: "draft" },
];

// STUB — replace when GET /admin/rag/docs is available
const docs = [
  { name: "CS101_Week1_Pointers.pdf", course: "CS101", size: "2.4 MB", status: "indexed" },
  { name: "CS201_Trees_Lecture.pdf", course: "CS201", size: "1.8 MB", status: "indexed" },
  { name: "CS101_Week3_OOP.pdf", course: "CS101", size: "3.1 MB", status: "indexing" },
];

const adminTabs = [
  { key: "stats", icon: "📊", label: "Evaluation" },
  { key: "models", icon: "🤖", label: "AI Models" },
  { key: "rag", icon: "📚", label: "RAG Docs" },
  { key: "users", icon: "👥", label: "Users" },
  { key: "courses", icon: "🎓", label: "Courses" },
];

export function AdminDashboard({ onNavigate, demoMode = false }: AdminDashboardProps) {
  const [tab, setTab] = useState("stats");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
    fetch(`${base}/health`)
      .then((r) => r.json())
      .then((data: { ready?: boolean }) => setHealthOk(Boolean(data.ready)))
      .catch(() => setHealthOk(false));
  }, []);

  const footer = (
    <Card style={{ padding: "10px 12px", marginTop: 12, borderRadius: 8 }}>
      <div style={{ ...mono, fontSize: 11, color: healthOk ? D.green : D.red }}>
        {healthOk === null ? "○ CHECKING..." : healthOk ? "● SYSTEM ONLINE" : "● SYSTEM OFFLINE"}
      </div>
      <div style={{ fontSize: 11, color: D.muted, marginTop: 3 }}>
        {healthOk === null
          ? "Contacting backend..."
          : healthOk
            ? "All services healthy"
            : "Backend unreachable"}
      </div>
    </Card>
  );

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
      <TopBar view="admin" onNavigate={onNavigate} demoMode={demoMode} />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar tabs={adminTabs} active={tab} onTab={setTab} footer={footer} />

        <div style={{ flex: 1, overflow: "auto", padding: 22 }}>
          {tab === "stats" && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                Evaluation dashboard <Tag color={D.muted}>STUB</Tag>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 12,
                  marginBottom: 18,
                }}
              >
                <Stat label="// sessions.today" value="211" sub="+18% from yesterday" />
                <Stat label="// hints.requested" value="61" sub="28.9% hint rate" color={D.yellow} />
                <Stat label="// problems.solved" value="150" sub="71% resolution rate" color={D.green} />
                <Stat label="// avg.session_min" value="24m" sub="↑ 3 min this week" color={D.blue} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "5fr 2fr", gap: 14 }}>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>
                    // sessions_this_week
                  </div>
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={sessionData}>
                      <CartesianGrid strokeDasharray="3 3" stroke={D.border} />
                      <XAxis dataKey="day" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <Tooltip {...chartTooltipStyle} />
                      <Area type="monotone" dataKey="sessions" stroke={D.orange} fill={`${D.orange}12`} strokeWidth={2} name="sessions" />
                      <Area type="monotone" dataKey="resolved" stroke={D.green} fill={`${D.green}08`} strokeWidth={2} name="resolved" />
                    </AreaChart>
                  </ResponsiveContainer>
                </Card>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>
                    // model_share
                  </div>
                  <ResponsiveContainer width="100%" height={130}>
                    <PieChart>
                      <Pie data={modelShare} cx="50%" cy="50%" outerRadius={54} dataKey="value" strokeWidth={0}>
                        {modelShare.map((m, i) => (
                          <Cell key={i} fill={m.color} />
                        ))}
                      </Pie>
                      <Tooltip {...chartTooltipStyle} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
                    {modelShare.map((m) => (
                      <div key={m.name} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                        <div style={{ width: 7, height: 7, borderRadius: "50%", background: m.color, flexShrink: 0 }} />
                        <span style={{ color: D.dim, flex: 1 }}>{m.name}</span>
                        <span style={{ color: D.text, ...mono }}>{m.value}%</span>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          )}

          {tab === "models" && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                AI model configuration <Tag color={D.muted}>STUB</Tag>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
                {models.map((m) => (
                  <Card
                    key={m.name}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 16,
                      borderColor: m.active ? D.orangeBorder : D.border,
                      background: m.active ? `${D.orange}05` : D.card,
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                        <span style={{ ...mono, fontSize: 13, fontWeight: 500 }}>{m.name}</span>
                        {m.active && <Tag>Active</Tag>}
                        <Tag color={D.muted}>{m.note}</Tag>
                      </div>
                      <div style={{ display: "flex", gap: 18 }}>
                        {[["Tier", m.tier], ["Speed", m.speed]].map(([k, v]) => (
                          <span key={k} style={{ fontSize: 12, color: D.muted }}>
                            {k}: <span style={{ color: D.dim }}>{v}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                    <Btn variant={m.active ? "ghost" : "primary"} small>
                      {m.active ? "✓ Active" : "Activate"}
                    </Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {tab === "rag" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  RAG document library <Tag color={D.muted}>STUB</Tag>
                </div>
                <Btn small>+ Upload document</Btn>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {docs.map((d) => (
                  <Card key={d.name} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 16px" }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>📄</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{d.name}</div>
                      <div style={{ fontSize: 11, color: D.muted, marginTop: 2 }}>
                        {d.course} · {d.size}
                      </div>
                    </div>
                    <Tag color={d.status === "indexed" ? D.green : D.yellow}>
                      {d.status === "indexed" ? "✓ indexed" : "⏳ indexing"}
                    </Tag>
                    <Btn variant="danger" small>
                      Remove
                    </Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {tab === "users" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  Professors <Tag color={D.muted}>STUB</Tag>
                </div>
                <Btn small>+ Add professor</Btn>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {professors.map((p) => (
                  <Card key={p.email} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 16px" }}>
                    <Avatar name={p.name.split(" ").pop() ?? p.name} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>{p.email}</div>
                    </div>
                    <Tag color={p.status === "active" ? D.green : D.yellow}>{p.status}</Tag>
                    <Btn variant="danger" small>
                      Remove
                    </Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {tab === "courses" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  Courses <Tag color={D.muted}>STUB</Tag>
                </div>
                <Btn small>+ Create course</Btn>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {courses.map((c) => (
                  <Card key={c.code} style={{ display: "flex", alignItems: "center", gap: 16 }}>
                    <div
                      style={{
                        background: D.orangeGlow,
                        border: `1px solid ${D.orangeBorder}`,
                        borderRadius: 6,
                        padding: "5px 11px",
                        ...mono,
                        fontSize: 13,
                        fontWeight: 600,
                        color: D.orange,
                        flexShrink: 0,
                      }}
                    >
                      {c.code}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>{c.name}</div>
                      <div style={{ fontSize: 12, color: D.muted, marginTop: 2 }}>Prof: {c.prof}</div>
                    </div>
                    <Tag color={c.status === "active" ? D.green : D.yellow}>{c.status}</Tag>
                    <Btn variant="ghost" small>
                      Manage
                    </Btn>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
