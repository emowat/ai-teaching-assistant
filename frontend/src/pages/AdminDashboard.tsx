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

const CUSTOM_MODEL_VALUE = "__custom__";
interface ModelOption {
  label: string;
  value: string;
}

const OPENAI_MODEL_OPTIONS: ModelOption[] = [
  { label: "gpt-5.4-mini", value: "gpt-5.4-mini" },
  { label: "gpt-5.4", value: "gpt-5.4" },
  { label: "gpt-5.5", value: "gpt-5.5" },
];
const COHERE_MODEL_OPTIONS: ModelOption[] = [
  { label: "command-r", value: "command-r" },
  { label: "command-r-plus", value: "command-r-plus" },
  { label: "command-xlarge-nightly", value: "command-xlarge-nightly" },
];
const BEDROCK_MODEL_OPTIONS: ModelOption[] = [
  { label: "Amazon Nova 2 Lite", value: "us.amazon.nova-2-lite-v1:0" },
  {
    label: "Anthropic Claude 3.5 Haiku",
    value: "us.anthropic.claude-3-5-haiku-20241022-v1:0",
  },
];
const OLLAMA_MODEL_OPTIONS: ModelOption[] = [
  { label: "qwen3.5:9b", value: "qwen3.5:9b" },
  { label: "llama3.1:8b", value: "llama3.1:8b" },
  { label: "llama3.2:3b", value: "llama3.2:3b" },
];

function getModelOptions(provider: LlmProvider): ModelOption[] {
  switch (provider) {
    case "openai":
      return OPENAI_MODEL_OPTIONS;
    case "cohere":
      return COHERE_MODEL_OPTIONS;
    case "bedrock":
      return BEDROCK_MODEL_OPTIONS;
    case "ollama":
      return OLLAMA_MODEL_OPTIONS;
    case "sagemaker":
      return [];
  }
}

function resolveModelValue(selected: string, customValue: string): string {
  return selected === CUSTOM_MODEL_VALUE ? customValue.trim() : selected;
}

function getDefaultModel(provider: LlmProvider): string {
  switch (provider) {
    case "openai":
      return OPENAI_MODEL_OPTIONS[0].value;
    case "cohere":
      return COHERE_MODEL_OPTIONS[0].value;
    case "bedrock":
      return BEDROCK_MODEL_OPTIONS[0].value;
    case "ollama":
      return OLLAMA_MODEL_OPTIONS[0].value;
    case "sagemaker":
      return "";
  }
}

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
  const [cohereConfigured, setCohereConfigured] = useState<boolean | null>(null);
  const [gradioAvailable, setGradioAvailable] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AdminLlmConfig | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [ragProvider, setRagProvider] = useState<LlmProvider>("cohere");
  const [ragModelChoice, setRagModelChoice] = useState("command-xlarge-nightly");
  const [ragCustomModel, setRagCustomModel] = useState("");
  const [chatProvider, setChatProvider] = useState<LlmProvider>("ollama");
  const [chatModelChoice, setChatModelChoice] = useState("qwen3.5:9b");
  const [chatCustomModel, setChatCustomModel] = useState("");
  const [showOpenaiSecretEditor, setShowOpenaiSecretEditor] = useState(false);
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("https://api.openai.com/v1");
  const gradioUrl = getGradioUrl();

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
    fetch(`${base}/health`)
      .then((r) => r.json())
      .then((data: { ready?: boolean; cohere_configured?: boolean }) => {
        setHealthOk(Boolean(data.ready));
        setCohereConfigured(data.cohere_configured ?? null);
      })
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
        const ragOptions = getModelOptions(data.rag.provider);
        const ragHasModel = ragOptions.some((option) => option.value === data.rag.model);
        setRagModelChoice(ragHasModel ? data.rag.model : CUSTOM_MODEL_VALUE);
        setRagCustomModel(ragHasModel ? "" : data.rag.model);
        setChatProvider(data.chat.provider);
        const chatOptions = getModelOptions(data.chat.provider);
        const chatHasModel = chatOptions.some((option) => option.value === data.chat.model);
        setChatModelChoice(chatHasModel ? data.chat.model : CUSTOM_MODEL_VALUE);
        setChatCustomModel(chatHasModel ? "" : data.chat.model);
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
      const nextRagModel = resolveModelValue(ragModelChoice, ragCustomModel);
      const nextChatModel = resolveModelValue(chatModelChoice, chatCustomModel);
      if (!nextRagModel) {
        if (ragProvider !== "sagemaker") {
          throw new Error("Select or enter a RAG model.");
        }
      }
      if (chatProvider !== "sagemaker" && !nextChatModel) {
        throw new Error("Select or enter a chat model.");
      }
      const payload = {
        rag: { provider: ragProvider, model: ragProvider === "sagemaker" ? "" : nextRagModel },
        chat: {
          provider: chatProvider,
          model: chatProvider === "sagemaker" ? "" : nextChatModel,
        },
        openai_base_url: openaiBaseUrl.trim() || null,
        ...(openaiApiKey.trim() ? { openai_api_key: openaiApiKey.trim() } : {}),
      };
      const data = await saveAdminLlmConfig(payload, accessToken);
      setConfig(data);
      setOpenaiApiKey("");
      setShowOpenaiSecretEditor(false);
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

  const renderModelPicker = (
    label: string,
    provider: LlmProvider,
    value: string,
    customValue: string,
    onValueChange: (next: string) => void,
    onCustomValueChange: (next: string) => void
  ) => {
    const options = getModelOptions(provider);
    if (provider === "sagemaker") {
      return (
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 12, color: D.muted }}>{label}</span>
          <div
            style={{
              background: D.surface,
              color: D.text,
              border: `1px solid ${D.border}`,
              borderRadius: 8,
              padding: "10px 12px",
              minHeight: 42,
              display: "flex",
              alignItems: "center",
            }}
          >
            <span style={{ fontSize: 13, color: D.dim }}>
              SageMaker uses the configured endpoint directly. No model name is required here.
            </span>
          </div>
        </label>
      );
    }

    return (
      <div style={{ display: "grid", gap: 6 }}>
        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 12, color: D.muted }}>{label}</span>
          <select
            value={value}
            onChange={(e) => onValueChange(e.target.value)}
            style={{
              background: D.bg,
              color: D.text,
              border: `1px solid ${D.border}`,
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            <option value={CUSTOM_MODEL_VALUE}>Custom...</option>
          </select>
        </label>
        {value === CUSTOM_MODEL_VALUE && (
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, color: D.muted }}>Custom model name</span>
            <input
              value={customValue}
              onChange={(e) => onCustomValueChange(e.target.value)}
              placeholder="Enter exact model name"
              style={{
                background: D.bg,
                color: D.text,
                border: `1px solid ${D.border}`,
                borderRadius: 8,
                padding: "10px 12px",
              }}
            />
          </label>
        )}
      </div>
    );
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
                        const nextOptions = getModelOptions(next);
                        const currentValue = resolveModelValue(ragModelChoice, ragCustomModel);
                        if (nextOptions.length === 0) {
                          setRagModelChoice(CUSTOM_MODEL_VALUE);
                          setRagCustomModel("");
                          return;
                        }
                        if (currentValue && nextOptions.some((option) => option.value === currentValue)) {
                          setRagModelChoice(currentValue);
                          setRagCustomModel("");
                          return;
                        }
                        setRagModelChoice(getDefaultModel(next));
                        setRagCustomModel("");
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
                      <option value="bedrock">Bedrock</option>
                    </select>
                  </label>
                  {renderModelPicker(
                    "RAG model",
                    ragProvider,
                    ragModelChoice,
                    ragCustomModel,
                    setRagModelChoice,
                    setRagCustomModel
                  )}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Chat provider</span>
                    <select
                      value={chatProvider}
                      onChange={(e) => {
                        const next = e.target.value as LlmProvider;
                        setChatProvider(next);
                        const nextOptions = getModelOptions(next);
                        const currentValue = resolveModelValue(chatModelChoice, chatCustomModel);
                        if (nextOptions.length === 0) {
                          setChatModelChoice(CUSTOM_MODEL_VALUE);
                          setChatCustomModel("");
                          return;
                        }
                        if (currentValue && nextOptions.some((option) => option.value === currentValue)) {
                          setChatModelChoice(currentValue);
                          setChatCustomModel("");
                          return;
                        }
                        setChatModelChoice(getDefaultModel(next));
                        setChatCustomModel("");
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
                      <option value="bedrock">Bedrock</option>
                    </select>
                  </label>
                  {renderModelPicker(
                    "Chat model",
                    chatProvider,
                    chatModelChoice,
                    chatCustomModel,
                    setChatModelChoice,
                    setChatCustomModel
                  )}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                  <div style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>
                      OpenAI secret {config?.openai_api_key_configured ? "(configured)" : "(not set)"}
                    </span>
                    {showOpenaiSecretEditor ? (
                      <>
                        <input
                          type="password"
                          value={openaiApiKey}
                          onChange={(e) => setOpenaiApiKey(e.target.value)}
                          placeholder="Paste a new OpenAI API key"
                          style={{
                            background: D.bg,
                            color: D.text,
                            border: `1px solid ${D.border}`,
                            borderRadius: 8,
                            padding: "10px 12px",
                          }}
                        />
                        <div style={{ fontSize: 11, color: D.muted }}>
                          The saved key is not shown. Leave this blank to keep the existing secret.
                        </div>
                      </>
                    ) : (
                      <div
                        style={{
                          background: D.surface,
                          color: D.text,
                          border: `1px solid ${D.border}`,
                          borderRadius: 8,
                          padding: "10px 12px",
                          minHeight: 42,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                        }}
                      >
                        <span style={{ fontSize: 13, color: D.dim }}>
                          {config?.openai_api_key_configured
                            ? "Configured on the backend"
                            : "Not configured yet"}
                        </span>
                        <Btn small variant="ghost" onClick={() => setShowOpenaiSecretEditor(true)}>
                          {config?.openai_api_key_configured ? "Replace key" : "Set key"}
                        </Btn>
                      </div>
                    )}
                  </div>
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
                      Current route: RAG <span style={{ color: D.text }}>{config.rag.provider}</span> /{" "}
                      {config.rag.provider !== "sagemaker" ? config.rag.model : "endpoint"} · Chat{" "}
                      <span style={{ color: D.text }}>{config.chat.provider}</span>
                      {config.chat.provider !== "sagemaker" ? ` / ${config.chat.model}` : " / endpoint"}
                    </span>
                  )}
                </div>

                {formError && <div style={{ color: D.red, fontSize: 12 }}>{formError}</div>}
                {formStatus && <div style={{ color: D.green, fontSize: 12 }}>{formStatus}</div>}
              </Card>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>RAG route</div>
                  <div style={{ ...mono, fontSize: 13 }}>
                    {config ? `${config.rag.provider}${config.rag.provider === "sagemaker" ? "" : ` / ${config.rag.model}`}` : "Loading..."}
                  </div>
                </Card>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Chat route</div>
                  <div style={{ ...mono, fontSize: 13 }}>
                    {config ? `${config.chat.provider}${config.chat.provider === "sagemaker" ? "" : ` / ${config.chat.model}`}` : "Loading..."}
                  </div>
                </Card>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>OpenAI secret</div>
                  <div style={{ ...mono, fontSize: 13 }}>
                    {config?.openai_api_key_configured ? "Configured" : "Not configured"}
                  </div>
                </Card>
                <Card>
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Cohere secret</div>
                  <div style={{ ...mono, fontSize: 13 }}>
                    {cohereConfigured === null
                      ? "Unknown"
                      : cohereConfigured
                        ? "Configured on backend"
                        : "Not configured"}
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
