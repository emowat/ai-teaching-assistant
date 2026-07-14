import { useEffect, useMemo, useState } from "react";
import { Btn, Card, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import { TopBar } from "../components/TopBar";
import { Sidebar, type SidebarTab } from "../components/Sidebar";
import type { AppView } from "../types/navigation";
import { getCodespacesFallbackUrl, getWeekLaunchUrl, isWeekLaunchReady } from "../data/codespaces";
import { getStudentBootstrap, type StudentBootstrapResponse } from "../api/studentBootstrapApi";
import type { SectionLaunchConfig } from "../api/sectionLaunchConfigsApi";
import { pickDefaultLaunchId, pickDefaultSection } from "../data/studentLaunch";
import { StudentMetricsDashboard } from "../components/StudentMetricsDashboard";

interface StudentInterfaceProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
  accessToken: string;
}

function launchConfigToWeek(config: SectionLaunchConfig) {
  return {
    id: config.launch_id,
    label: config.label,
    repoUrl: config.repo_url,
    templateUrl: config.template_url,
    defaultBranch: config.default_branch,
    enabled: config.enabled,
  };
}

const fallbackCodespacesUrl = getCodespacesFallbackUrl();

export function StudentInterface({
  onNavigate,
  allowedViews,
  onSignOut,
  accessToken,
}: StudentInterfaceProps) {
  const [bootstrap, setBootstrap] = useState<StudentBootstrapResponse | null>(null);
  const [bootstrapToken, setBootstrapToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [selectedLaunchId, setSelectedLaunchId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"launch" | "metrics">("launch");

  useEffect(() => {
    if (!accessToken) return;

    let cancelled = false;

    void getStudentBootstrap(accessToken)
      .then((nextBootstrap) => {
        if (cancelled) return;
        setBootstrap(nextBootstrap);
        setBootstrapToken(accessToken);
        setSelectedSectionId((current) => current ?? pickDefaultSection(nextBootstrap));
        const defaultSectionId = pickDefaultSection(nextBootstrap);
        const defaultSection =
          nextBootstrap.sections.find((section) => section.section_id === defaultSectionId) ??
          nextBootstrap.sections[0] ??
          null;
        setSelectedLaunchId(
          (current) =>
            current ??
            pickDefaultLaunchId(defaultSection?.launch_configs ?? []) ??
            null
        );
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setBootstrap(null);
          setBootstrapToken(accessToken);
          setSelectedSectionId(null);
          setSelectedLaunchId(null);
          setError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const activeBootstrap = bootstrapToken === accessToken ? bootstrap : null;
  const isBootstrapLoading = Boolean(accessToken) && bootstrapToken !== accessToken;
  const activeBootstrapError = accessToken ? error : null;

  const selectedSection = useMemo(
    () => activeBootstrap?.sections.find((section) => section.section_id === selectedSectionId) ?? null,
    [activeBootstrap, selectedSectionId],
  );
  const launchConfigs = useMemo(
    () => selectedSection?.launch_configs ?? [],
    [selectedSection],
  );
  const selectedLaunchConfig = useMemo(
    () =>
      launchConfigs.find((config) => config.launch_id === selectedLaunchId) ??
      launchConfigs.find((config) => config.enabled) ??
      launchConfigs[0] ??
      null,
    [launchConfigs, selectedLaunchId],
  );

  const launchUrl = useMemo(() => {
    if (!selectedLaunchConfig) {
      return fallbackCodespacesUrl;
    }
    return getWeekLaunchUrl(launchConfigToWeek(selectedLaunchConfig));
  }, [selectedLaunchConfig]);

  const isConfigured = launchUrl !== fallbackCodespacesUrl;
  const isLaunchReady = selectedLaunchConfig ? isWeekLaunchReady(launchConfigToWeek(selectedLaunchConfig)) : false;
  const hasEnabledSections = Boolean(activeBootstrap?.sections.length);

  const openLaunchTarget = () => {
    window.open(launchUrl, "_blank", "noopener,noreferrer");
  };

  const stepCards = [
    {
      title: "1. Pick your section",
      body:
        "Your active sections now come from the backend bootstrap payload, not browser storage. The extension and the web launcher see the same assignments.",
    },
    {
      title: "2. Open the configured launch target",
      body:
        "Each section carries its own Codespaces launch config. Open the active launch option for the section you are working on.",
    },
    {
      title: "3. Use the extension inside Codespaces",
      body:
        "The VS Code extension, compile tools, and live tutor continue to run inside the Codespace. The web app is the launcher and status surface.",
    },
  ];

  const studentTabs: SidebarTab[] = [
    { key: "launch", icon: "🚀", label: "Codespace Launch" },
    { key: "metrics", icon: "📊", label: "My Analytics" },
  ];

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
        view="student"
        onNavigate={onNavigate}
        allowedViews={allowedViews}
        onSignOut={onSignOut}
      />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar tabs={studentTabs} active={activeTab} onTab={(key) => setActiveTab(key as "launch" | "metrics")} />

        <div style={{ flex: 1, overflow: "auto", padding: "40px 24px 56px" }}>
          <div style={{ maxWidth: 1080, margin: "0 auto" }}>
          
          {activeTab === 'launch' ? (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
                <Tag>Backend-backed student launch</Tag>
                <span style={{ ...mono, fontSize: 12, color: D.muted }}>
                  Student bootstrap is the source of truth
                </span>
              </div>

          {isBootstrapLoading ? (
            <Card style={{ padding: 24, marginBottom: 18 }}>
              <div style={{ fontSize: 14, color: D.muted }}>Loading student access...</div>
            </Card>
          ) : activeBootstrapError ? (
            <Card
              style={{
                marginBottom: 18,
                padding: 24,
                border: `1px solid ${D.red}24`,
                background: `${D.red}08`,
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
                Student access unavailable
              </div>
              <div style={{ color: D.muted, lineHeight: 1.7, marginBottom: 16 }}>
                {activeBootstrapError}
              </div>
              <Btn onClick={() => window.location.reload()}>Retry student access</Btn>
            </Card>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(320px, 1.2fr) minmax(280px, 0.8fr)",
                gap: 18,
                alignItems: "start",
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
                  Launch your{" "}
                  <span style={{ color: D.orange }}>section-specific Codespace</span>
                </h1>
                <p style={{ color: D.muted, lineHeight: 1.8, margin: "0 0 22px" }}>
                  The browser editor and local week config are gone from the primary path.
                  Student access is now resolved from Aurora and the same backend data powers
                  the VS Code extension.
                </p>

                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
                  <Btn onClick={openLaunchTarget} disabled={!isConfigured || !isLaunchReady}>
                    Open launch target
                  </Btn>
                </div>

                <div style={{ display: "grid", gap: 14, marginBottom: 20 }}>
                  <div>
                    <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>
                      Active section
                    </div>
                    <select
                      aria-label="Active section"
                      value={selectedSection?.section_id ?? ""}
                      onChange={(event) => {
                        const nextSectionId = event.target.value || null;
                        setSelectedSectionId(nextSectionId);
                        const nextSection =
                          activeBootstrap?.sections.find((section) => section.section_id === nextSectionId) ?? null;
                        setSelectedLaunchId(
                          nextSection ? pickDefaultLaunchId(nextSection.launch_configs) : null,
                        );
                      }}
                      disabled={!hasEnabledSections}
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
                      {(activeBootstrap?.sections ?? []).map((section) => (
                        <option key={section.section_id} value={section.section_id}>
                          {section.display_name} · {section.term || "no term"}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>
                      Launch target
                    </div>
                    <select
                      aria-label="Launch target"
                      value={selectedLaunchConfig?.launch_id ?? ""}
                      onChange={(event) => setSelectedLaunchId(event.target.value || null)}
                      disabled={!launchConfigs.length}
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
                      {launchConfigs.map((config) => (
                        <option key={config.launch_id} value={config.launch_id}>
                          {config.label}
                          {config.enabled ? "" : " (disabled)"}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {!hasEnabledSections && (
                  <div
                    style={{
                      padding: "12px 14px",
                      borderRadius: 10,
                      border: `1px solid ${D.red}24`,
                      background: `${D.red}08`,
                      color: D.text,
                      fontSize: 13,
                      lineHeight: 1.6,
                      marginBottom: 20,
                    }}
                  >
                    No active student section is assigned to this account yet. Contact your
                    instructor or an admin to finish provisioning.
                  </div>
                )}

                {selectedSection && (
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
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{selectedSection.display_name}</div>
                    <div style={{ color: D.muted }}>
                      Course: <code>{selectedSection.course_id}</code>
                      <br />
                      Section: <code>{selectedSection.section_id}</code>
                      <br />
                      Membership: <code>{selectedSection.membership_status}</code>
                    </div>
                  </div>
                )}

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12,
                  }}
                >
                  <Card style={{ padding: 14 }}>
                    <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Student</div>
                    <div style={{ fontWeight: 600 }}>{activeBootstrap?.user.display_name}</div>
                    <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
                      {activeBootstrap?.user.email}
                    </div>
                  </Card>
                  <Card style={{ padding: 14 }}>
                    <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Launch readiness</div>
                    <div style={{ fontWeight: 600 }}>{isLaunchReady ? "Ready" : "Not ready"}</div>
                    <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
                      {selectedLaunchConfig ? selectedLaunchConfig.label : "No launch target selected"}
                    </div>
                  </Card>
                </div>
              </Card>

              <div style={{ display: "grid", gap: 18 }}>
                <Card style={{ padding: 22 }}>
                  <div style={{ ...mono, fontSize: 11, color: D.muted, marginBottom: 14 }}>
                    // launch details
                  </div>
                  {selectedLaunchConfig ? (
                    <div style={{ display: "grid", gap: 10 }}>
                      <div style={{ fontSize: 18, fontWeight: 600 }}>{selectedLaunchConfig.label}</div>
                      <div style={{ fontSize: 13, color: D.muted, lineHeight: 1.7 }}>
                        Repo: <code>{selectedLaunchConfig.repo_url || "not set"}</code>
                        <br />
                        Template: <code>{selectedLaunchConfig.template_url || "not set"}</code>
                        <br />
                        Branch: <code>{selectedLaunchConfig.default_branch}</code>
                      </div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <Tag color={selectedLaunchConfig.enabled ? D.green : D.muted}>
                          {selectedLaunchConfig.enabled ? "enabled" : "disabled"}
                        </Tag>
                        <Tag color={D.blue}>sort {selectedLaunchConfig.sort_order}</Tag>
                      </div>
                      <div style={{ fontSize: 12, color: D.muted, lineHeight: 1.7 }}>
                        Launch URL:
                        <br />
                        <code>{launchUrl}</code>
                      </div>
                    </div>
                  ) : (
                    <div style={{ color: D.muted, lineHeight: 1.7 }}>
                      No launch target is configured for this section yet.
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
                      ["Section launch config", "saved in Aurora"],
                      ["RAG endpoint", "deployed rag_eng API URL"],
                      ["VS Code extension", "uses the same Cognito session"],
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

                <Card style={{ padding: 20 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
                    What the backend now controls
                  </div>
                  <div style={{ color: D.muted, fontSize: 13, lineHeight: 1.7 }}>
                    Active sections, launch targets, and access state now come from Aurora.
                    If a section changes in the database, both the web launcher and the VS Code
                    extension will see the same configuration.
                  </div>
                </Card>
              </div>
            </div>
          )}

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
          </>
          ) : (
            <StudentMetricsDashboard accessToken={accessToken} />
          )}
        </div>
      </div>
    </div>
    </div>
  );
}
