import { useMemo, useState } from "react";
import { Btn, Card, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";
import {
  getCodespacesFallbackUrl,
  getDefaultWeekId,
  getWeekLaunchUrl,
  isWeekLaunchReady,
  loadWeekLaunchConfigs,
} from "../data/codespaces";

interface StudentInterfaceProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
}

const fallbackCodespacesUrl = getCodespacesFallbackUrl();

export function StudentInterface({
  onNavigate,
  allowedViews,
  onSignOut,
}: StudentInterfaceProps) {
  const weeks = useMemo(() => loadWeekLaunchConfigs(), []);
  const [selectedWeekId, setSelectedWeekId] = useState<string>(() =>
    getDefaultWeekId(weeks)
  );

  const selectedWeek = useMemo(
    () => weeks.find((week) => week.id === selectedWeekId && week.enabled) ?? weeks.find((week) => week.enabled),
    [selectedWeekId, weeks]
  );

  const codespacesUrl = useMemo(() => {
    if (selectedWeek) {
      return getWeekLaunchUrl(selectedWeek);
    }
    return getCodespacesFallbackUrl();
  }, [selectedWeek]);

  const isConfigured = codespacesUrl !== fallbackCodespacesUrl;
  const isLaunchReady = selectedWeek ? isWeekLaunchReady(selectedWeek) : false;

  const openCodespaces = () => {
    window.open(codespacesUrl, "_blank", "noopener,noreferrer");
  };

  const enabledWeeks = weeks.filter((week) => week.enabled);
  const hasEnabledWeeks = enabledWeeks.length > 0;

  const stepCards = [
    {
      title: "1. Open the assignment in Codespaces",
      body:
        "Your coursework now lives in the GitHub repo. Open the template or assignment repo in Codespaces and let GitHub create the workspace for you.",
    },
    {
      title: "2. Use the VS Code extension",
      body:
        "The CodingRabbit extension loads inside the Codespace and talks to the deployed rag_eng API. That is where the Socratic tutor lives now.",
    },
    {
      title: "3. Compile in the Codespaces terminal",
      body:
        "Use the built-in terminal, g++, make, and debugger tools inside the container. The old browser sandbox is no longer the student path.",
    },
  ];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        background:
          "linear-gradient(180deg, rgba(255,253,248,0.98) 0%, rgba(248,243,234,0.98) 100%)",
        color: D.text,
        fontFamily: "var(--font-sans)",
      }}
    >
      <TopBar
        view="student"
        onNavigate={onNavigate}
        allowedViews={allowedViews}
        onSignOut={onSignOut}
      />

      <div style={{ flex: 1, overflow: "auto", padding: "40px 24px 56px" }}>
        <div style={{ maxWidth: 1040, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
            <Tag>Codespaces-first student flow</Tag>
            <span style={{ ...mono, fontSize: 12, color: D.muted }}>
              Monaco editor removed from the primary path
            </span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: 18,
            }}
          >
            <Card style={{ padding: 28 }}>
              <div style={{ ...mono, fontSize: 12, color: D.orange, marginBottom: 10 }}>
                // student workspace
              </div>
              <h1
                style={{
                  fontSize: 40,
                  lineHeight: 1.05,
                  margin: "0 0 14px",
                  letterSpacing: -1,
                }}
              >
                Open your assignment in{" "}
                <span style={{ color: D.orange }}>GitHub Codespaces</span>
              </h1>
              <p style={{ color: D.muted, lineHeight: 1.8, margin: "0 0 22px" }}>
                The browser editor, file explorer, and compile panel have been retired
                from the main student route. Students now work inside the Codespace
                itself, where the VS Code extension, terminal, and file tree are already
                available.
              </p>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
                <Btn onClick={openCodespaces} disabled={!hasEnabledWeeks || !isLaunchReady}>
                  Open Codespaces
                </Btn>
                <Btn
                  variant="ghost"
                  onClick={() =>
                    selectedWeek?.repoUrl && window.open(selectedWeek.repoUrl, "_blank", "noopener,noreferrer")
                  }
                  disabled={!selectedWeek?.repoUrl}
                >
                  Open week repo ↗
                </Btn>
              </div>

              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>
                  Select the week you are working on
                </div>
                <select
                  value={selectedWeek?.id ?? ""}
                  onChange={(event) => setSelectedWeekId(event.target.value)}
                  disabled={!hasEnabledWeeks}
                  style={{
                    width: "100%",
                    background: D.card,
                    border: `1px solid ${D.border}`,
                    color: D.text,
                    borderRadius: 8,
                    padding: "10px 12px",
                    fontSize: 13,
                  }}
                >
                  {enabledWeeks.map((week) => (
                    <option key={week.id} value={week.id}>
                      {week.label}
                    </option>
                  ))}
                </select>
              </div>

              {!hasEnabledWeeks && (
                <div
                  style={{
                    padding: "12px 14px",
                    borderRadius: 10,
                    border: `1px solid ${D.red}40`,
                    background: `${D.red}10`,
                    color: D.text,
                    fontSize: 13,
                    lineHeight: 1.6,
                    marginBottom: 20,
                  }}
                >
                  No week is enabled yet. Ask the professor to enable a week in the
                  Professor dashboard before opening Codespaces.
                </div>
              )}

              {selectedWeek && (
                <div
                  style={{
                    padding: "12px 14px",
                    borderRadius: 10,
                    border: `1px solid ${D.border}`,
                    background: D.surface,
                    marginBottom: 20,
                    lineHeight: 1.6,
                    fontSize: 13,
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{selectedWeek.label}</div>
                  <div style={{ color: D.muted }}>
                    Repo: <code>{selectedWeek.repoUrl}</code>
                    <br />
                    Template: <code>{selectedWeek.templateUrl}</code>
                    <br />
                    Branch: <code>{selectedWeek.defaultBranch}</code>
                  </div>
                </div>
              )}

              {selectedWeek && !isLaunchReady && (
                <div
                  style={{
                    padding: "12px 14px",
                    borderRadius: 10,
                    border: `1px solid ${D.yellow}40`,
                    background: `${D.yellow}12`,
                    color: D.text,
                    fontSize: 13,
                    lineHeight: 1.6,
                    marginBottom: 20,
                  }}
                >
                  This week is enabled but not launch-ready yet. Add a repo URL or
                  template URL in the Professor dashboard before launching.
                </div>
              )}

              {!isConfigured && (
                <div
                  style={{
                    padding: "12px 14px",
                    borderRadius: 10,
                    border: `1px solid ${D.yellow}40`,
                    background: `${D.yellow}12`,
                    color: D.text,
                    fontSize: 13,
                    lineHeight: 1.6,
                  }}
                >
                  Set <code>VITE_CODESPACES_TEMPLATE_URL</code> or{" "}
                  <code>VITE_CODESPACES_REPO_URL</code> in the repo root{" "}
                  <code>.env</code> as a fallback for weeks that do not define an override.
                </div>
              )}
            </Card>

            <Card style={{ padding: 22 }}>
              <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>
                // required environment
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                {[
                  ["GitHub Codespaces", "enabled for the org or class"],
                  ["Assignment repo", "template or starter repo"],
                  ["RAG endpoint", "deployed rag_eng API URL"],
                  ["Extension", "preinstalled in the devcontainer"],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      padding: "10px 12px",
                      borderRadius: 8,
                      border: `1px solid ${D.border}`,
                      background: D.surface,
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
                    <div style={{ fontSize: 12, color: D.muted, textAlign: "right" }}>
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 16,
              marginTop: 18,
            }}
          >
            {stepCards.map((card) => (
              <Card key={card.title} style={{ padding: 20 }}>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
                  {card.title}
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.7, color: D.muted }}>{card.body}</div>
              </Card>
            ))}
          </div>

          <Card style={{ padding: 20, marginTop: 18 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              What stays in the web app
            </div>
            <div style={{ color: D.muted, fontSize: 13, lineHeight: 1.7 }}>
              Admin and professor dashboards remain here. Students use Codespaces for
              editing and terminal work; the web app is now a launcher and status surface
              instead of a browser IDE.
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
