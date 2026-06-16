import { useEffect, useMemo, useState } from "react";
import { checkGradioAvailable, getGradioUrl } from "../api/gradioApi";
import {
  getAdminLlmConfig,
  restartBackend,
  saveAdminLlmConfig,
  type AdminLlmConfig,
  type LlmProvider,
} from "../api/adminLlmApi";
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
import { Sidebar, type SidebarTab } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";

interface AdminDashboardProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
  accessToken: string;
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

const modelShare = [
  { name: "Ollama", value: 58, color: D.orange },
  { name: "SageMaker", value: 27, color: D.blue },
  { name: "OpenAI", value: 15, color: D.green },
];

// STUB — replace when model config API is available
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

const baseAdminTabs: SidebarTab[] = [
  { key: "stats", icon: "📊", label: "Evaluation" },
  { key: "models", icon: "🤖", label: "AI Models" },
  { key: "rag", icon: "📚", label: "RAG Docs" },
  { key: "users", icon: "👥", label: "Users" },
  { key: "courses", icon: "🎓", label: "Courses" },
];

export function AdminDashboard({
  onNavigate,
  allowedViews,
  onSignOut,
  accessToken,
}: AdminDashboardProps) {
  const [tab, setTab] = useState("stats");
  const [healthOk, setHealthOk] = useState<boolean | null>(null);
  const [gradioAvailable, setGradioAvailable] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AdminLlmConfig | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [ragProvider, setRagProvider] = useState<LlmProvider>("cohere");
  const [ragModel, setRagModel] = useState("command-xlarge-nightly");
  const [chatProvider, setChatProvider] = useState<LlmProvider>("ollama");
  const [chatModel, setChatModel] = useState("qwen3.5:9b");
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("https://api.openai.com/v1");
  const gradioUrl = getGradioUrl();

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
    fetch(`${base}/health`)
      .then((r) => r.json())
      .then((data: { ready?: boolean }) => setHealthOk(Boolean(data.ready)))
      .catch(() => setHealthOk(false));
  }, []);

  useEffect(() => {
    let cancelled = false;

    const probeGradio = () => {
      void checkGradioAvailable().then((ok) => {
        if (!cancelled) setGradioAvailable(ok);
      });
    };

    probeGradio();
    const intervalId = window.setInterval(probeGradio, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;
    void getAdminLlmConfig(accessToken)
      .then((data) => {
        if (cancelled) return;
        setConfig(data);
        setRagProvider(data.rag.provider);
        setRagModel(data.rag.model);
        setChatProvider(data.chat.provider);
        setChatModel(data.chat.model);
        setOpenaiBaseUrl(data.openai_base_url || "https://api.openai.com/v1");
      })
      .catch((err: Error) => {
        if (!cancelled) setFormError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const adminTabs = useMemo<SidebarTab[]>(() => {
    const gradioDisabled = gradioAvailable !== true;
    const gradioTitle =
      gradioAvailable === null
        ? "Checking Gradio availability..."
        : gradioAvailable
          ? "Open backend diagnostic console"
          : "Gradio is not running — start rag_eng to enable";

    const backendConsoleTab: SidebarTab = {
      key: "backend-console",
      icon: "🖥",
      label: "Backend Diagnostic Console",
      disabled: gradioDisabled,
      title: gradioTitle,
    };
    const ragIndex = baseAdminTabs.findIndex((t) => t.key === "rag");
    return [
      ...baseAdminTabs.slice(0, ragIndex + 1),
      backendConsoleTab,
      ...baseAdminTabs.slice(ragIndex + 1),
    ];
  }, [gradioAvailable]);

  const activeTab = tab === "backend-console" && gradioAvailable === false ? "stats" : tab;

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

  const handleSaveConfig = async () => {
    setSaving(true);
    setFormError(null);
    setFormStatus(null);
    try {
      const payload = {
        rag: { provider: ragProvider, model: ragModel.trim() },
        chat: { provider: chatProvider, model: chatModel.trim() },
        openai_base_url: openaiBaseUrl.trim() || null,
        ...(openaiApiKey.trim() ? { openai_api_key: openaiApiKey.trim() } : {}),
      };
      const data = await saveAdminLlmConfig(payload, accessToken);
      setConfig(data);
      setOpenaiApiKey("");
      setFormStatus("Configuration saved.");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to save configuration.");
    } finally {
      setSaving(false);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    setFormError(null);
    setFormStatus(null);
    try {
      const result = await restartBackend(accessToken);
      setFormStatus(result.message);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Restart failed.");
    } finally {
      setRestarting(false);
    }
  };

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
      <TopBar
        view="admin"
        onNavigate={onNavigate}
        allowedViews={allowedViews}
        onSignOut={onSignOut}
      />
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar tabs={adminTabs} active={activeTab} onTab={setTab} footer={footer} />

        <div
          style={{
            flex: 1,
            overflow: "auto",
            padding:
              activeTab === "backend-console"
                ? 0
                : 22,
          }}
        >
          {activeTab === "backend-console" && gradioAvailable && (
            <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "12px 22px",
                  borderBottom: `1px solid ${D.border}`,
                  flexShrink: 0,
                }}
              >
                <div style={{ fontSize: 16, fontWeight: 600 }}>Backend Diagnostic Console</div>
                <Btn
                  small
                  variant="ghost"
                  onClick={() => window.open(gradioUrl, "_blank", "noopener,noreferrer")}
                >
                  Open in new tab ↗
                </Btn>
              </div>
              <iframe
                src={gradioUrl}
                title="Backend Diagnostic Console"
                style={{
                  flex: 1,
                  width: "100%",
                  border: "none",
                  minHeight: 480,
                  background: D.surface,
                }}
              />
            </div>
          )}

          {activeTab === "stats" && (
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

          {activeTab === "models" && (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                AI model configuration
                <span style={{ marginLeft: 8 }}>
                  {config?.restart_command_configured ? (
                    <Tag color={D.green}>Live reload ready</Tag>
                  ) : (
                    <Tag color={D.yellow}>Restart command unset</Tag>
                  )}
                </span>
              </div>
              <Card style={{ display: "grid", gap: 16, marginBottom: 16 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>RAG provider</span>
                    <select
                      value={ragProvider}
                      onChange={(e) => {
                        const next = e.target.value as LlmProvider;
                        setRagProvider(next);
                        if (next === "openai" && (!ragModel || ragModel === "command-xlarge-nightly")) {
                          setRagModel("gpt-5.4-mini");
                        }
                      }}
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    >
                      <option value="cohere">Cohere</option>
                      <option value="openai">OpenAI</option>
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>RAG model</span>
                    <input
                      value={ragModel}
                      onChange={(e) => setRagModel(e.target.value)}
                      placeholder="command-xlarge-nightly"
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    />
                  </label>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Chat provider</span>
                    <select
                      value={chatProvider}
                      onChange={(e) => {
                        const next = e.target.value as LlmProvider;
                        setChatProvider(next);
                        if (next === "openai" && (!chatModel || chatModel === "qwen3.5:9b")) {
                          setChatModel("gpt-5.4-mini");
                        }
                      }}
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    >
                      <option value="ollama">Ollama</option>
                      <option value="sagemaker">SageMaker</option>
                      <option value="openai">OpenAI</option>
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Chat model</span>
                    <input
                      value={chatModel}
                      onChange={(e) => setChatModel(e.target.value)}
                      placeholder="gpt-5.4-mini"
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    />
                  </label>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>
                      OpenAI API key {config?.openai_api_key_configured ? "(saved)" : "(not set)"}
                    </span>
                    <input
                      type="password"
                      value={openaiApiKey}
                      onChange={(e) => setOpenaiApiKey(e.target.value)}
                      placeholder="sk-..."
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>OpenAI base URL</span>
                    <input
                      value={openaiBaseUrl}
                      onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                      placeholder="https://api.openai.com/v1"
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    />
                  </label>
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                  <Btn variant="primary" small onClick={handleSaveConfig} disabled={saving || restarting}>
                    {saving ? "Saving..." : "Save configuration"}
                  </Btn>
                  <Btn variant="ghost" small onClick={handleRestart} disabled={saving || restarting}>
                    {restarting ? "Restarting..." : "Apply / restart"}
                  </Btn>
                  {config && (
                    <span style={{ fontSize: 12, color: D.muted }}>
                      Current route: RAG <span style={{ color: D.text }}>{config.rag.provider}</span> / Chat{" "}
                      <span style={{ color: D.text }}>{config.chat.provider}</span>
                    </span>
                  )}
                </div>

                {formError && <div style={{ color: D.red, fontSize: 12 }}>{formError}</div>}
                {formStatus && <div style={{ color: D.green, fontSize: 12 }}>{formStatus}</div>}
              </Card>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>RAG route</div>
                  <div style={{ ...mono, fontSize: 13 }}>{config ? `${config.rag.provider} / ${config.rag.model}` : "Loading..."}</div>
                </Card>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Chat route</div>
                  <div style={{ ...mono, fontSize: 13 }}>{config ? `${config.chat.provider} / ${config.chat.model}` : "Loading..."}</div>
                </Card>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>OpenAI secret</div>
                  <div style={{ ...mono, fontSize: 13 }}>
                    {config?.openai_api_key_configured ? "Configured" : "Not configured"}
                  </div>
                </Card>
              </div>
            </div>
          )}

          {activeTab === "rag" && (
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

          {activeTab === "users" && (
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

          {activeTab === "courses" && (
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
