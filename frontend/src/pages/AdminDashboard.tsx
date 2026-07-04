import { useEffect, useMemo, useState } from "react";
import { checkGradioAvailable, getGradioUrl } from "../api/gradioApi";
import {
  getAdminLlmConfig,
  restartBackend,
  saveAdminLlmConfig,
  getAdminDashboardStats,
  getAdminDashboardFeedback,
  triggerChatLogExport,
  type DashboardStats,
  type FeedbackEntry,
  type AdminLlmConfig,
  type LlmProvider,
} from "../api/adminLlmApi";
import { listAdminCourses, type AdminCourse } from "../api/adminCoursesApi";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Btn, Card, Stat, Tag } from "../design/atoms";
import { chartTooltipStyle, D, mono } from "../design/tokens";
import { Sidebar, type SidebarTab } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import { CourseManagementPanel } from "../components/admin/CourseManagementPanel";
import { SectionManagementPanel } from "../components/admin/SectionManagementPanel";
import { UserManagementPanel } from "../components/admin/UserManagementPanel";
import { RagDocsPanel } from "../components/admin/RagDocsPanel";
import type { AppView } from "../types/navigation";

interface AdminDashboardProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
  accessToken: string;
}



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
    label: "Anthropic Claude Sonnet 4.6",
    value: "us.anthropic.claude-sonnet-4-6",
  },
  {
    label: "Anthropic Claude Haiku 4.5",
    value: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  },
];
const OLLAMA_MODEL_OPTIONS: ModelOption[] = [
  { label: "qwen3.5:9b", value: "qwen3.5:9b" },
  { label: "llama3.1:8b", value: "llama3.1:8b" },
  { label: "llama3.2:3b", value: "llama3.2:3b" },
];

const HEALTH_POLL_INTERVAL_SECONDS = (() => {
  const parsed = Number(import.meta.env.VITE_HEALTH_POLL_INTERVAL_SECONDS ?? "15");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 15;
})();

interface BackendHealthResponse {
  ready?: boolean;
  qdrant_configured?: boolean;
  course_registry_configured?: boolean;
  cohere_configured?: boolean;
  openai_configured?: boolean;
  bedrock_configured?: boolean;
  qdrant_reachable?: boolean;
  course_registry_reachable?: boolean;
  cohere_reachable?: boolean;
  openai_reachable?: boolean;
  bedrock_reachable?: boolean;
  message?: string;
}

interface HealthState {
  loading: boolean;
  refreshing: boolean;
  healthy: boolean | null;
  snapshot: BackendHealthResponse | null;
  checkedAt: string | null;
  error: string | null;
}

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

function describeHealthService(configured?: boolean, reachable?: boolean): string {
  if (configured === false) return "not configured";
  if (reachable === false) return "configured, unreachable";
  if (configured === true && reachable === true) return "configured, reachable";
  return "unknown";
}

function formatHealthTooltip(state: HealthState): string {
  const lines: string[] = [];

  if (state.loading) {
    lines.push("Checking backend health...");
  } else if (state.healthy) {
    lines.push("Backend health: healthy");
  } else {
    lines.push("Backend health: unavailable or degraded");
  }

  if (state.error) {
    lines.push(`Error: ${state.error}`);
  }

  if (state.snapshot?.message) {
    lines.push(`Message: ${state.snapshot.message}`);
  }

  const snapshot = state.snapshot;
  if (snapshot) {
    lines.push(`Qdrant: ${describeHealthService(snapshot.qdrant_configured, snapshot.qdrant_reachable)}`);
    lines.push(
      `Course registry: ${describeHealthService(
        snapshot.course_registry_configured,
        snapshot.course_registry_reachable,
      )}`,
    );
    lines.push(`Cohere: ${describeHealthService(snapshot.cohere_configured, snapshot.cohere_reachable)}`);
    lines.push(`OpenAI: ${describeHealthService(snapshot.openai_configured, snapshot.openai_reachable)}`);
    lines.push(`Bedrock: ${describeHealthService(snapshot.bedrock_configured, snapshot.bedrock_reachable)}`);
  }

  if (state.checkedAt) {
    lines.push(`Last checked (UTC): ${state.checkedAt}`);
  }

  return lines.join("\n");
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

const baseAdminTabs: SidebarTab[] = [
  { key: "users", icon: "👥", label: "Users" },
  { key: "classes", icon: "🏫", label: "Classes" },
  { key: "courses", icon: "🎓", label: "Courses" },
  { key: "rag", icon: "📚", label: "RAG Docs" },
  { key: "stats", icon: "📊", label: "Evaluation" },
  { key: "feedback", icon: "💬", label: "Feedback" },
  { key: "models", icon: "🤖", label: "AI Models" },
];

export function AdminDashboard({
  onNavigate,
  allowedViews,
  onSignOut,
  accessToken,
}: AdminDashboardProps) {
  const [tab, setTab] = useState("backend-console");
  const [healthState, setHealthState] = useState<HealthState>({
    loading: true,
    refreshing: false,
    healthy: null,
    snapshot: null,
    checkedAt: null,
    error: null,
  });
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

  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [courseFilter, setCourseFilter] = useState<string>("all");

  useEffect(() => {
    if (!accessToken) return;
    void listAdminCourses(accessToken).then(setCourses).catch(console.error);
  }, [accessToken]);

  useEffect(() => {
    const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
    let cancelled = false;
    let activeController: AbortController | null = null;

    const pollHealth = async (initialLoad: boolean) => {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;

      setHealthState((prev) => ({
        ...prev,
        loading: prev.snapshot === null && prev.checkedAt === null,
        refreshing: !initialLoad && prev.snapshot !== null,
        error: null,
      }));

      try {
        const response = await fetch(`${base}/health`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = (await response.json()) as BackendHealthResponse;
        if (cancelled) return;
        const checkedAt = new Date().toISOString();
        setHealthState({
          loading: false,
          refreshing: false,
          healthy: Boolean(data.ready),
          snapshot: data,
          checkedAt,
          error: null,
        });
        setCohereConfigured(data.cohere_configured ?? null);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        const message = err instanceof Error ? err.message : "Unable to load backend health.";
        setHealthState((prev) => ({
          loading: false,
          refreshing: false,
          healthy: false,
          snapshot: prev.snapshot,
          checkedAt: new Date().toISOString(),
          error: message,
        }));
      }
    };

    void pollHealth(true);
    const intervalId = window.setInterval(() => {
      void pollHealth(false);
    }, HEALTH_POLL_INTERVAL_SECONDS * 1000);

    return () => {
      cancelled = true;
      activeController?.abort();
      window.clearInterval(intervalId);
    };
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
    return [...baseAdminTabs, backendConsoleTab];
  }, [gradioAvailable]);

  const [timezoneFilter, setTimezoneFilter] = useState<string>("America/Los_Angeles");
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);
  const [statsError, setStatsError] = useState<boolean>(false);
  const [exportStartDate, setExportStartDate] = useState("");
  const [exportEndDate, setExportEndDate] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  const [feedbackData, setFeedbackData] = useState<FeedbackEntry[]>([]);
  const [feedbackError, setFeedbackError] = useState<boolean>(false);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;

    const fetchStats = () => {
      getAdminDashboardStats(accessToken, courseFilter === "all" ? undefined : courseFilter, timezoneFilter)
        .then((data) => {
          if (!cancelled) {
            setDashboardStats(data);
            setStatsError(false);
          }
        })
        .catch((err) => {
          console.error("Failed to fetch dashboard stats", err);
          if (!cancelled) setStatsError(true);
        });
    };

    fetchStats();
    const intervalId = window.setInterval(fetchStats, 60000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [accessToken, courseFilter, timezoneFilter]);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;

    const fetchFeedback = () => {
      getAdminDashboardFeedback(accessToken, courseFilter === "all" ? undefined : courseFilter, 50)
        .then((data) => {
          if (!cancelled) {
            setFeedbackData(data.feedback);
            setFeedbackError(false);
          }
        })
        .catch((err) => {
          console.error("Failed to fetch feedback", err);
          if (!cancelled) setFeedbackError(true);
        });
    };

    fetchFeedback();
    const intervalId = window.setInterval(fetchFeedback, 60000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [accessToken, courseFilter]);

  const handleExport = async () => {
    if (!accessToken) return;
    setExporting(true);
    setExportResult(null);
    try {
      const res = await triggerChatLogExport(accessToken, courseFilter, exportStartDate, exportEndDate, timezoneFilter);
      setExportResult(`Success: ${res.message} (Total records: ${res.total_records})`);
    } catch (err: any) {
      setExportResult(`Error: ${err.message}`);
    } finally {
      setExporting(false);
    }
  };

    const activeTab = tab;
  const healthBadgeColor = healthState.loading || healthState.refreshing
    ? D.yellow
    : healthState.healthy
      ? D.green
      : D.red;
  const healthBadgeLabel = healthState.loading
    ? "○ CHECKING..."
    : healthState.refreshing
      ? "↻ CHECKING..."
      : healthState.healthy
        ? "● SYSTEM ONLINE"
        : "● SYSTEM OFFLINE";
  const healthSubtext = healthState.loading
    ? "Contacting backend..."
    : healthState.refreshing
      ? "Refreshing backend health..."
      : healthState.healthy
        ? "All services healthy"
        : healthState.error
          ? healthState.snapshot
            ? "Backend responded, but one or more services are unavailable"
            : "Backend unreachable"
          : "One or more services are unavailable";
  const healthTooltip = useMemo(() => formatHealthTooltip(healthState), [healthState]);

  const footer = (
    <Card style={{ padding: "10px 12px", marginTop: 12, borderRadius: 8 }}>
      <div
        title={healthTooltip}
        style={{ cursor: "help" }}
      >
        <div style={{ ...mono, fontSize: 11, color: healthBadgeColor }}>
          {healthBadgeLabel}
        </div>
        <div style={{ fontSize: 11, color: D.muted, marginTop: 3 }}>{healthSubtext}</div>
        <div style={{ fontSize: 10, color: D.dim, marginTop: 3 }}>
          Polling every {HEALTH_POLL_INTERVAL_SECONDS}s
        </div>
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
        background:
          "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
        color: D.text,
        fontFamily: "var(--font-sans)",
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

          {activeTab === "backend-console" && !gradioAvailable && (
            <div style={{ padding: 22 }}>
              <Card style={{ display: "grid", gap: 8, maxWidth: 640 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  Backend Diagnostic Console
                </div>
                <div style={{ fontSize: 13, color: D.muted, lineHeight: 1.5 }}>
                  The Gradio diagnostics app is not available right now. Start the
                  `rag_eng` backend with the diagnostic console enabled to use this
                  tab.
                </div>
                <div style={{ fontSize: 12, color: D.dim }}>
                  The sidebar will keep this tab selected by default once the backend
                  console is available.
                </div>
              </Card>
            </div>
          )}

                    {activeTab === "stats" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Live Operational Dashboard</div>
                <div style={{ display: "flex", gap: 12 }}>
                  <select
                    value={timezoneFilter}
                    onChange={(e) => setTimezoneFilter(e.target.value)}
                    style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${D.border}`, background: D.surface, color: D.text, fontSize: 13, cursor: "pointer" }}
                  >
                    <option value="America/Los_Angeles">US Pacific (PT)</option>
                    <option value="America/Denver">US Mountain (MT)</option>
                    <option value="America/Chicago">US Central (CT)</option>
                    <option value="America/New_York">US Eastern (ET)</option>
                    <option value="UTC">UTC</option>
                  </select>
                  <select
                    value={courseFilter}
                    onChange={(e) => setCourseFilter(e.target.value)}
                    style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${D.border}`, background: D.surface, color: D.text, fontSize: 13, cursor: "pointer" }}
                  >
                    <option value="all">All Courses</option>
                    {courses.map(c => (
                      <option key={c.course_id} value={c.course_id}>{c.course_id.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 8 }}>// Daily:</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 18 }}>
                <Stat label="Sessions" value={dashboardStats?.sessions_today?.toString() ?? "..."} />
                <Stat label="Requests" value={dashboardStats?.requests_today?.toString() ?? "..."} color={D.blue} />
                <Stat label="Chat(secs)" value={dashboardStats?.chat_seconds_today !== undefined ? `${dashboardStats.chat_seconds_today}s` : "..."} color={D.purple} />
                <Stat label="Editor(secs)" value={dashboardStats?.editor_seconds_today !== undefined ? `${dashboardStats.editor_seconds_today}s` : "..."} color={D.purple} />
                <Stat label="Terminal(secs)" value={dashboardStats?.terminal_seconds_today !== undefined ? `${dashboardStats.terminal_seconds_today}s` : "..."} color={D.purple} />
                <Stat label="Rewards" value={dashboardStats?.total_rewards_given?.toString() ?? "..."} color={D.green} />
                <Stat label="Style Nudged" value={dashboardStats?.total_style_nudges?.toString() ?? "..."} color={D.orange} />
                <Stat label="System Errors" value={statsError ? "ERR_FETCH" : dashboardStats?.system_errors?.toString() ?? "..."} color={D.red} />
              </div>

              <Card style={{ marginBottom: 18 }}>
                <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// export_chat_logs</div>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
                  <label style={{ display: "grid", gap: 6, flex: 1, minWidth: 150 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Start Date (Optional)</span>
                    <input type="date" value={exportStartDate} onChange={(e) => setExportStartDate(e.target.value)} style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${D.border}`, background: D.surface, color: D.text, fontSize: 13 }} />
                  </label>
                  <label style={{ display: "grid", gap: 6, flex: 1, minWidth: 150 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>End Date (Optional)</span>
                    <input type="date" value={exportEndDate} onChange={(e) => setExportEndDate(e.target.value)} style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${D.border}`, background: D.surface, color: D.text, fontSize: 13 }} />
                  </label>
                  <Btn onClick={handleExport} disabled={exporting}>
                    {exporting ? "Exporting..." : "Export to JSON"}
                  </Btn>
                </div>
                {exportResult && (
                  <div style={{ marginTop: 12, fontSize: 12, color: exportResult.startsWith("Error") ? D.red : D.green }}>
                    {exportResult}
                  </div>
                )}
              </Card>

              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14, marginBottom: 14 }}>
                <Card>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                    <div style={{ ...mono, fontSize: 11, color: D.muted }}>// request_volume (7 days)</div>
                    <div style={{ fontSize: 11, color: D.muted }}>
                      <span style={{ color: D.blue }}>■</span> Homework Assist &nbsp;&nbsp;
                      <span style={{ color: D.orange }}>■</span> Study Assist
                    </div>
                  </div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={dashboardStats?.session_data || []}>
                      <CartesianGrid strokeDasharray="3 3" stroke={D.border} vertical={false} />
                      <XAxis dataKey="day" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <Tooltip {...chartTooltipStyle} />
                      <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: D.muted }} />
                      {dashboardStats?.homework_keys?.map((k, i) => (
                        <Bar key={k} dataKey={k} name={k.split(": ")[1] || k} stackId="homework" fill={[D.blue, D.purple, "#0ea5e9"][i % 3]} />
                      ))}
                      {dashboardStats?.study_keys?.map((k, i) => (
                        <Bar key={k} dataKey={k} name={k.split(": ")[1] || k} stackId="study" fill={[D.orange, D.yellow, D.red][i % 3]} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </Card>

                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// guardrail_interventions</div>
                  <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                    <div style={{ flex: 1, padding: 12, background: `${D.red}10`, borderRadius: 6, border: `1px solid ${D.red}30` }}>
                      <div style={{ fontSize: 24, fontWeight: 600, color: D.red }}>{dashboardStats?.guardrails?.input_blocks || 0}</div>
                      <div style={{ fontSize: 11, color: D.dim, ...mono }}>Input Blocks</div>
                    </div>
                    <div style={{ flex: 1, padding: 12, background: `${D.orange}10`, borderRadius: 6, border: `1px solid ${D.orange}30` }}>
                      <div style={{ fontSize: 24, fontWeight: 600, color: D.orange }}>{dashboardStats?.guardrails?.output_blocks || 0}</div>
                      <div style={{ fontSize: 11, color: D.dim, ...mono }}>Output Blocks</div>
                    </div>
                  </div>
                  <ResponsiveContainer width="100%" height={120}>
                    <PieChart>
                      <Pie
                        data={dashboardStats?.guardrails?.violation_types || []}
                        cx="50%" cy="50%"
                        outerRadius={50}
                        dataKey="value"
                        nameKey="name"
                        strokeWidth={0}
                      >
                        {(dashboardStats?.guardrails?.violation_types || []).map((_, i) => (
                          <Cell key={i} fill={[D.red, D.orange, D.yellow, D.green, D.blue, D.purple][i % 6]} />
                        ))}
                      </Pie>
                      <Tooltip {...chartTooltipStyle} />
                      <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: D.muted }} layout="vertical" verticalAlign="middle" align="right" />
                    </PieChart>
                  </ResponsiveContainer>
                </Card>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// rewards_and_nudges (7 days)</div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={dashboardStats?.weekly_rewards || []}>
                      <CartesianGrid strokeDasharray="3 3" stroke={D.border} vertical={false} />
                      <XAxis dataKey="day" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <Tooltip {...chartTooltipStyle} />
                      <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: D.muted }} />
                      <Bar dataKey="rewards_given" name="Rewards" fill={D.green} />
                      <Bar dataKey="style_nudges" name="Style Nudged" fill={D.orange} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>

                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// engagement_time (7 days)</div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={dashboardStats?.weekly_engagement || []}>
                      <CartesianGrid strokeDasharray="3 3" stroke={D.border} vertical={false} />
                      <XAxis dataKey="day" stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <YAxis stroke={D.muted} tick={{ fontSize: 11, fill: D.muted }} />
                      <Tooltip {...chartTooltipStyle} />
                      <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: D.muted }} />
                      <Bar dataKey="chat_seconds" name="Chat (s)" fill={D.purple} />
                      <Bar dataKey="editor_seconds" name="Editor (s)" fill={D.blue} />
                      <Bar dataKey="terminal_seconds" name="Terminal (s)" fill={D.orange} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14 }}>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// latency_metrics (ms)</div>
                  <table style={{ width: "100%", fontSize: 13, textAlign: "left", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${D.border}`, color: D.muted }}>
                        <th style={{ padding: 8, fontWeight: 500 }}>Phase</th>
                        <th style={{ padding: 8, fontWeight: 500 }}>P50</th>
                        <th style={{ padding: 8, fontWeight: 500 }}>P90</th>
                        <th style={{ padding: 8, fontWeight: 500 }}>P99</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ borderBottom: `1px solid ${D.border}` }}>
                        <td style={{ padding: 8 }}>Input Guardrail</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.input_guardrail?.p50 || 0}</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.input_guardrail?.p90 || 0}</td>
                        <td style={{ padding: 8, ...mono, color: (dashboardStats?.latencies?.input_guardrail?.p99 || 0) > 1000 ? D.red : D.text }}>{dashboardStats?.latencies?.input_guardrail?.p99 || 0}</td>
                      </tr>
                      <tr style={{ borderBottom: `1px solid ${D.border}` }}>
                        <td style={{ padding: 8 }}>Retrieval (RAG)</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.rag?.p50 || 0}</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.rag?.p90 || 0}</td>
                        <td style={{ padding: 8, ...mono, color: (dashboardStats?.latencies?.rag?.p99 || 0) > 2000 ? D.red : D.text }}>{dashboardStats?.latencies?.rag?.p99 || 0}</td>
                      </tr>
                      <tr style={{ borderBottom: `1px solid ${D.border}` }}>
                        <td style={{ padding: 8 }}>LLM Generation</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.llm?.p50 || 0}</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.llm?.p90 || 0}</td>
                        <td style={{ padding: 8, ...mono, color: (dashboardStats?.latencies?.llm?.p99 || 0) > 10000 ? D.red : D.text }}>{dashboardStats?.latencies?.llm?.p99 || 0}</td>
                      </tr>
                      <tr>
                        <td style={{ padding: 8 }}>Output Guardrail</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.output_guardrail?.p50 || 0}</td>
                        <td style={{ padding: 8, ...mono }}>{dashboardStats?.latencies?.output_guardrail?.p90 || 0}</td>
                        <td style={{ padding: 8, ...mono, color: (dashboardStats?.latencies?.output_guardrail?.p99 || 0) > 1000 ? D.red : D.text }}>{dashboardStats?.latencies?.output_guardrail?.p99 || 0}</td>
                      </tr>
                    </tbody>
                  </table>
                </Card>
                <Card>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>// model_share (7 days)</div>
                  <ResponsiveContainer width="100%" height={130}>
                    <PieChart>
                      <Pie
                        data={dashboardStats?.model_share || []}
                        cx="50%" cy="50%"
                        outerRadius={54}
                        dataKey="value"
                        nameKey="name"
                        strokeWidth={0}
                      >
                        {(dashboardStats?.model_share || []).map((_, i) => (
                          <Cell key={i} fill={[D.blue, D.orange, D.green, D.red, D.purple, D.yellow][i % 6]} />
                        ))}
                      </Pie>
                      <Tooltip {...chartTooltipStyle} />
                      <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: D.muted }} layout="vertical" verticalAlign="middle" align="right" />
                    </PieChart>
                  </ResponsiveContainer>
                </Card>
              </div>
            </div>
          )}

          {activeTab === "feedback" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Student Feedback</div>
                <div style={{ display: "flex", gap: 12 }}>
                  <select
                    value={courseFilter}
                    onChange={(e) => setCourseFilter(e.target.value)}
                    style={{ padding: "6px 12px", borderRadius: 6, border: `1px solid ${D.border}`, background: D.surface, color: D.text, fontSize: 13 }}
                  >
                    <option value="all">All Courses</option>
                    {courses.map(c => (
                      <option key={c.course_id} value={c.course_id}>{c.course_id.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
              </div>

              {feedbackError ? (
                <div style={{ color: D.red, padding: 12, background: `${D.red}10`, borderRadius: 8 }}>
                  Failed to load feedback data.
                </div>
              ) : feedbackData.length === 0 ? (
                <div style={{ color: D.muted, padding: 24, textAlign: "center" }}>
                  No Feedback Received
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {feedbackData.map((f, i) => (
                    <Card key={i} style={{ display: "flex", flexDirection: "column", gap: 12, padding: 16 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 16 }}>{f.rating === "positive" ? "👍" : "👎"}</span>
                          <span style={{ fontWeight: 600, color: f.rating === "positive" ? D.green : D.red }}>
                            {f.rating === "positive" ? "Positive" : "Negative"}
                          </span>
                          {f.explanation && (
                            <span style={{ fontSize: 14, color: D.text, marginLeft: 8 }}>"{f.explanation}"</span>
                          )}
                        </div>
                        <div style={{ ...mono, fontSize: 11, color: D.muted }}>
                          {f.created_at ? new Date(f.created_at).toLocaleString() : "Unknown date"} • Turn {f.turn_index}
                        </div>
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                        {f.rag_sources && f.rag_sources.length > 0 && (
                          <>
                            <div style={{ fontSize: 12, color: D.muted, ...mono }}>// rag_sources</div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                              {f.rag_sources.map(src => (
                                <Tag key={src} color={D.orange}>{src}</Tag>
                              ))}
                            </div>
                          </>
                        )}

                        <div style={{ fontSize: 12, color: D.muted, ...mono, marginTop: 4 }}>// student_message</div>
                        <div style={{ background: `${D.blue}08`, padding: 12, borderRadius: 6, fontSize: 13, borderLeft: `3px solid ${D.blue}` }}>
                          {f.student_message || <span style={{ color: D.muted, fontStyle: "italic" }}>No message text</span>}
                        </div>

                        {f.cot && Object.keys(f.cot).length > 0 && (
                          <>
                            <div style={{ fontSize: 12, color: D.muted, ...mono, marginTop: 4 }}>// chain_of_thought</div>
                            <div style={{ background: D.surface, padding: 12, borderRadius: 6, fontSize: 12, border: `1px solid ${D.border}` }}>
                              {Object.entries(f.cot).map(([key, val]) => (
                                <div key={key} style={{ marginBottom: 4 }}>
                                  <span style={{ fontWeight: 600, color: D.muted }}>{key}: </span>
                                  <span style={{ color: D.text }}>{String(val)}</span>
                                </div>
                              ))}
                            </div>
                          </>
                        )}

                        <div style={{ fontSize: 12, color: D.muted, ...mono, marginTop: 4 }}>// ai_response</div>
                        <div style={{ background: `${D.purple}08`, padding: 12, borderRadius: 6, fontSize: 13, borderLeft: `3px solid ${D.purple}`, whiteSpace: "pre-wrap" }}>
                          {f.ai_message || <span style={{ color: D.muted, fontStyle: "italic" }}>No response text</span>}
                        </div>
                      </div>
                      <div style={{ fontSize: 11, color: D.dim, ...mono, textAlign: "right", marginTop: 8 }}>Session ID: {f.session_id}</div>
                    </Card>
                  ))}
                </div>
              )}
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
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 16,
                  }}
                >
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

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 16,
                  }}
                >
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

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                    gap: 16,
                  }}
                >
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

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 10,
                }}
              >
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
            <RagDocsPanel accessToken={accessToken} />
          )}

          {activeTab === "users" && (
            <UserManagementPanel accessToken={accessToken} />
          )}

          {activeTab === "classes" && (
            <SectionManagementPanel accessToken={accessToken} />
          )}

          {activeTab === "courses" && (
            <CourseManagementPanel accessToken={accessToken} />
          )}
        </div>
      </div>
    </div>
  );
}
