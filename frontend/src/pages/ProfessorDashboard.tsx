import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  listProfessorSectionStudents,
  listProfessorSections,
  type ProfessorSectionStudent,
  type ProfessorSectionSummary,
} from "../api/professorSectionsApi";
import {
  listProfessorSectionLaunchConfigs,
  replaceProfessorSectionLaunchConfigs,
  type SectionLaunchConfig,
} from "../api/sectionLaunchConfigsApi";
import { Avatar, Btn, Card, Stat, Tag } from "../design/atoms";
import { chartTooltipStyle, D, mono } from "../design/tokens";
import { Sidebar } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";
import { getWeekLaunchUrl, isWeekLaunchReady } from "../data/codespaces";

interface ProfessorDashboardProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
  accessToken: string;
}

const weekData = [
  { week: "W1", sessions: 4, hints: 1 },
  { week: "W2", sessions: 6, hints: 2 },
  { week: "W3", sessions: 6, hints: 2 },
  { week: "W4", sessions: 7, hints: 3 },
  { week: "W5", sessions: 6, hints: 3 },
];

const profTabs = [
  { key: "overview", icon: "📋", label: "Overview" },
  { key: "launches", icon: "🚀", label: "Launches" },
  { key: "students", icon: "👥", label: "Students" },
  { key: "analytics", icon: "📊", label: "Analytics" },
];

const inputStyle = {
  background: D.card,
  border: `1px solid ${D.border}`,
  color: D.text,
  borderRadius: 8,
  padding: "8px 10px",
  fontSize: 13,
  width: "100%",
};

function emptyLaunchConfig(index = 0): SectionLaunchConfig {
  return {
    launch_id: `launch-${index + 1}`,
    label: `Launch ${index + 1}`,
    repo_url: "",
    template_url: "",
    default_branch: "main",
    enabled: true,
    sort_order: index,
  };
}

function toWeekLaunchConfig(config: SectionLaunchConfig) {
  return {
    id: config.launch_id,
    label: config.label,
    repoUrl: config.repo_url,
    templateUrl: config.template_url,
    defaultBranch: config.default_branch,
    enabled: config.enabled,
  };
}

function formatLastSession(value: string): string {
  if (!value) {
    return "No sessions yet";
  }
  return value;
}

export function ProfessorDashboard({
  onNavigate,
  allowedViews,
  onSignOut,
  accessToken,
}: ProfessorDashboardProps) {
  const [tab, setTab] = useState("overview");
  const [sections, setSections] = useState<ProfessorSectionSummary[]>([]);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [students, setStudents] = useState<ProfessorSectionStudent[]>([]);
  const [launchConfigs, setLaunchConfigs] = useState<SectionLaunchConfig[]>([]);
  const [launchConfigsSectionId, setLaunchConfigsSectionId] = useState<string | null>(null);
  const [loadingSections, setLoadingSections] = useState(true);
  const [studentFetchComplete, setStudentFetchComplete] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [studentError, setStudentError] = useState<string | null>(null);
  const [launchConfigError, setLaunchConfigError] = useState<string | null>(null);
  const [launchConfigStatus, setLaunchConfigStatus] = useState<string | null>(null);
  const [savingLaunchConfigs, setSavingLaunchConfigs] = useState(false);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);
  const selectedSection = useMemo(
    () => sections.find((section) => section.section_id === selectedSectionId) ?? null,
    [sections, selectedSectionId]
  );
  const selectedStudent = useMemo(
    () => students.find((student) => student.user_id === selectedStudentId) ?? null,
    [selectedStudentId, students]
  );
  const activeLaunchConfigs = useMemo(
    () => (launchConfigsSectionId === selectedSectionId ? launchConfigs : []),
    [launchConfigs, launchConfigsSectionId, selectedSectionId],
  );
  const readyLaunchConfigCount = useMemo(
    () =>
      activeLaunchConfigs.reduce(
        (count, config) =>
          count + (isWeekLaunchReady(toWeekLaunchConfig(config)) ? 1 : 0),
        0,
      ),
    [activeLaunchConfigs],
  );
  const loadingLaunchConfigs = Boolean(
    selectedSectionId &&
      accessToken &&
      launchConfigsSectionId !== selectedSectionId &&
      !launchConfigError
  );
  const loadingStudents = Boolean(selectedSectionId) && !studentFetchComplete && !studentError;

  useEffect(() => {
    let cancelled = false;

    void listProfessorSections(accessToken)
      .then((nextSections) => {
        if (cancelled) return;
        setSections(nextSections);
        setSelectedSectionId((current) => current ?? nextSections[0]?.section_id ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setSections([]);
          setSectionError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingSections(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  useEffect(() => {
    if (!selectedSectionId || !accessToken) {
      return;
    }

    let cancelled = false;

    void listProfessorSectionLaunchConfigs(selectedSectionId, accessToken)
      .then((nextConfigs) => {
        if (cancelled) return;
        setLaunchConfigs(nextConfigs);
        setLaunchConfigsSectionId(selectedSectionId);
        setLaunchConfigStatus(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setLaunchConfigError(err.message);
          setLaunchConfigsSectionId(selectedSectionId);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId]);

  useEffect(() => {
    if (!selectedSectionId) {
      return;
    }

    let cancelled = false;

    void listProfessorSectionStudents(selectedSectionId, accessToken)
      .then((nextStudents) => {
        if (cancelled) return;
        setStudents(nextStudents);
        setSelectedStudentId(nextStudents[0]?.user_id ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setStudents([]);
          setStudentError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setStudentFetchComplete(true);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId]);

  const handleSectionChange = (nextSectionId: string | null) => {
    setSelectedSectionId(nextSectionId);
    setStudents([]);
    setSelectedStudentId(null);
    setStudentError(null);
    setStudentFetchComplete(false);
    setLaunchConfigError(null);
    setLaunchConfigStatus(null);
  };

  const rosterSummary = selectedSection
    ? `${selectedSection.student_count} students · ${selectedSection.ta_count} TAs · ${selectedSection.professor_count} professors`
    : "Select a section to view the roster";

  const updateLaunchConfig = (launchId: string, patch: Partial<SectionLaunchConfig>) => {
    setLaunchConfigs((current) =>
      current.map((config) =>
        config.launch_id === launchId ? { ...config, ...patch } : config
      )
    );
  };

  const addLaunchConfig = () => {
    setLaunchConfigs((current) => [...current, emptyLaunchConfig(current.length)]);
  };

  const removeLaunchConfig = (launchId: string) => {
    setLaunchConfigs((current) =>
      current.filter((config) => config.launch_id !== launchId)
    );
  };

  const resetLaunchConfigs = () => {
    if (!selectedSectionId) {
      return;
    }
    setLaunchConfigStatus(null);
    setLaunchConfigError(null);
    setLaunchConfigsSectionId(null);
    void listProfessorSectionLaunchConfigs(selectedSectionId, accessToken)
      .then((nextConfigs) => {
        setLaunchConfigs(nextConfigs);
        setLaunchConfigsSectionId(selectedSectionId);
      })
      .catch((err: Error) => {
        setLaunchConfigError(err.message);
        setLaunchConfigsSectionId(selectedSectionId);
      });
  };

  const saveLaunchConfigs = async () => {
    if (!selectedSectionId) {
      return;
    }

    setSavingLaunchConfigs(true);
    setLaunchConfigError(null);
    setLaunchConfigStatus(null);

    try {
      const cleaned = launchConfigs.map((config, index) => {
        const launchId = config.launch_id.trim();
        const label = config.label.trim();
        if (!launchId) {
          throw new Error(`Launch ID is required for row ${index + 1}.`);
        }
        if (!label) {
          throw new Error(`Label is required for row ${index + 1}.`);
        }
        return {
          ...config,
          launch_id: launchId,
          label,
          repo_url: config.repo_url.trim(),
          template_url: config.template_url.trim(),
          default_branch: config.default_branch.trim() || "main",
          sort_order: index,
        };
      });

      const seen = new Set<string>();
      for (const config of cleaned) {
        if (seen.has(config.launch_id)) {
          throw new Error(`Duplicate launch ID: ${config.launch_id}.`);
        }
        seen.add(config.launch_id);
      }

      const updated = await replaceProfessorSectionLaunchConfigs(
        selectedSectionId,
        accessToken,
        cleaned
      );
      setLaunchConfigs(updated);
      setLaunchConfigsSectionId(selectedSectionId);
      setLaunchConfigStatus("Saved launch configs.");
    } catch (err) {
      setLaunchConfigError(err instanceof Error ? err.message : "Unable to save launch configs.");
    } finally {
      setSavingLaunchConfigs(false);
    }
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
        view="professor"
        onNavigate={onNavigate}
        allowedViews={allowedViews}
        onSignOut={onSignOut}
      />

      <div
        style={{
          padding: "9px 20px",
          borderBottom: `1px solid ${D.border}`,
          display: "flex",
          alignItems: "center",
          gap: 14,
          background: D.surface,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 13, color: D.muted }}>Section:</span>
        <select
          aria-label="Teaching section"
          value={selectedSectionId ?? ""}
          onChange={(event) => handleSectionChange(event.target.value || null)}
          style={{
            background: D.card,
            border: `1px solid ${D.border}`,
            color: D.text,
            borderRadius: 6,
            padding: "5px 10px",
            fontSize: 13,
            cursor: "pointer",
            minWidth: 280,
          }}
        >
          {loadingSections && <option value="">Loading sections...</option>}
          {!loadingSections && sections.length === 0 && <option value="">No sections found</option>}
          {sections.map((section) => (
            <option key={section.section_id} value={section.section_id}>
              {section.section_id} · {section.display_name}
            </option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        <Tag color={D.green}>{selectedSection ? selectedSection.course_id : "no section"}</Tag>
        <Tag color={D.red}>{selectedSection ? `${selectedSection.student_count} students` : "no roster"}</Tag>
        <Tag color={D.muted}>Section roster</Tag>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar
          tabs={profTabs}
          active={tab}
          onTab={(next) => {
            setTab(next);
            setSelectedStudentId(null);
          }}
        />

        <div style={{ flex: 1, overflow: "auto", padding: 22 }}>
          {tab === "overview" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                {selectedSection ? selectedSection.display_name : "Section overview"}
              </div>
              {sectionError && (
                <Card style={{ marginBottom: 14, color: D.red, fontSize: 12 }}>{sectionError}</Card>
              )}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                  gap: 12,
                  marginBottom: 18,
                }}
              >
                <Stat
                  label="// enrolled"
                  value={selectedSection?.student_count ?? 0}
                  sub={rosterSummary}
                  color={D.green}
                />
                <Stat
                  label="// ta_count"
                  value={selectedSection?.ta_count ?? 0}
                  sub="assigned helpers"
                  color={D.blue}
                />
                <Stat
                  label="// professor_count"
                  value={selectedSection?.professor_count ?? 0}
                  sub="section owners"
                  color={D.orange}
                />
                <Stat
                  label="// section_state"
                  value={selectedSection?.is_active ? "active" : "inactive"}
                  sub={selectedSection?.term || "no term"}
                  color={selectedSection?.is_active ? D.green : D.yellow}
                />
              </div>
              <Card style={{ marginBottom: 18, display: "grid", gap: 8 }}>
                <div style={{ fontSize: 12, color: D.muted }}>Section context</div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>
                  {selectedSection ? selectedSection.section_id : "No section selected"}
                </div>
                <div style={{ fontSize: 12, color: D.dim }}>
                  {selectedSection
                    ? `${selectedSection.course_id} · ${selectedSection.course_display_name} · ${selectedSection.term || "n/a"}`
                    : "Choose a section from the selector above."}
                </div>
                <div style={{ fontSize: 12, color: D.dim, lineHeight: 1.5 }}>
                  Students use the launch configs in this section to enter the workspace. Keep the
                  selected section and its launch setup aligned with the roster below.
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Tag color={selectedSection?.is_active ? D.green : D.red}>
                    {selectedSection?.is_active ? "active section" : "inactive section"}
                  </Tag>
                  <Tag color={D.blue}>
                    {activeLaunchConfigs.length} launch config
                    {activeLaunchConfigs.length === 1 ? "" : "s"}
                  </Tag>
                  <Tag color={D.orange}>
                    {readyLaunchConfigCount} ready
                    {readyLaunchConfigCount === 1 ? "" : " configs"}
                  </Tag>
                </div>
              </Card>
              <Card>
                <div style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}>Current section</div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  {selectedSection ? selectedSection.section_id : "No section selected"}
                </div>
                <div style={{ fontSize: 12, color: D.dim, marginTop: 4 }}>
                  {selectedSection
                    ? `${selectedSection.course_id} · ${selectedSection.course_display_name} · ${selectedSection.term || "n/a"}`
                    : "Choose a section from the selector above."}
                </div>
              </Card>
            </div>
          ) : tab === "launches" ? (
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
                  Section launch config <Tag color={D.green}>Aurora-backed</Tag>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Btn small variant="ghost" onClick={addLaunchConfig} disabled={!selectedSectionId}>
                    Add launch option
                  </Btn>
                  <Btn small variant="ghost" onClick={resetLaunchConfigs} disabled={!selectedSectionId}>
                    Reload
                  </Btn>
                  <Btn
                    small
                    onClick={() => void saveLaunchConfigs()}
                    disabled={!selectedSectionId || savingLaunchConfigs || loadingLaunchConfigs}
                  >
                    {savingLaunchConfigs ? "Saving..." : "Save launch configs"}
                  </Btn>
                </div>
              </div>
              {launchConfigError && (
                <Card style={{ marginBottom: 12, color: D.red, fontSize: 12 }}>
                  {launchConfigError}
                </Card>
              )}
              {launchConfigStatus && (
                <Card style={{ marginBottom: 12, color: D.green, fontSize: 12 }}>
                  {launchConfigStatus}
                </Card>
              )}
              {loadingLaunchConfigs ? (
                <Card>Loading launch configs...</Card>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {activeLaunchConfigs.length === 0 && (
                    <Card style={{ color: D.muted, fontSize: 13, lineHeight: 1.7 }}>
                      No launch configs are saved for this section yet. Add one to define the
                      Codespaces launch target students should use.
                    </Card>
                  )}
                  {activeLaunchConfigs.map((launchConfig, index) => (
                    <Card key={launchConfig.launch_id} style={{ display: "grid", gap: 10 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>
                          Launch option {index + 1}
                        </div>
                        <Tag color={launchConfig.enabled ? D.green : D.muted}>
                          {launchConfig.enabled ? "Enabled" : "Disabled"}
                        </Tag>
                        <Btn small variant="danger" onClick={() => removeLaunchConfig(launchConfig.launch_id)}>
                          Remove
                        </Btn>
                      </div>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>Launch ID</span>
                        <input
                          value={launchConfig.launch_id}
                          onChange={(event) =>
                            updateLaunchConfig(launchConfig.launch_id, {
                              launch_id: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>Label</span>
                        <input
                          value={launchConfig.label}
                          onChange={(event) =>
                            updateLaunchConfig(launchConfig.launch_id, {
                              label: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Student repo URL for this launch
                        </span>
                        <input
                          value={launchConfig.repo_url}
                          onChange={(event) =>
                            updateLaunchConfig(launchConfig.launch_id, {
                              repo_url: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Codespaces template URL
                        </span>
                        <input
                          value={launchConfig.template_url}
                          onChange={(event) =>
                            updateLaunchConfig(launchConfig.launch_id, {
                              template_url: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Default branch for Codespaces
                        </span>
                        <input
                          value={launchConfig.default_branch}
                          onChange={(event) =>
                            updateLaunchConfig(launchConfig.launch_id, {
                              default_branch: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: D.muted }}>
                          <input
                            type="checkbox"
                            checked={launchConfig.enabled}
                            onChange={(event) =>
                              updateLaunchConfig(launchConfig.launch_id, {
                                enabled: event.target.checked,
                              })
                            }
                          />
                          Enabled
                        </label>
                        <div style={{ fontSize: 11, color: D.muted }}>
                          Launch URL:{" "}
                          <code>{getWeekLaunchUrl(toWeekLaunchConfig(launchConfig))}</code>
                        </div>
                        <div style={{ fontSize: 11, color: D.muted }}>
                          Status:{" "}
                          {isWeekLaunchReady(toWeekLaunchConfig(launchConfig))
                            ? "launch ready"
                            : "missing repo/template URL"}
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          ) : tab === "students" ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ fontSize: 18, fontWeight: 600 }}>
                Students for {selectedSection ? selectedSection.display_name : "selected section"}{" "}
                <Tag color={D.muted}>
                  {loadingStudents ? "loading" : "active memberships only"}
                </Tag>
              </div>
              <Card style={{ fontSize: 12, color: D.muted, lineHeight: 1.7 }}>
                This roster shows active student memberships for the selected section and includes
                live session usage from Aurora-backed telemetry.
              </Card>
              {studentError && <Card style={{ color: D.red, fontSize: 12 }}>{studentError}</Card>}
              {selectedStudent ? (
                <Card style={{ display: "grid", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Avatar name={selectedStudent.display_name || selectedStudent.email} size={38} />
                    <div style={{ display: "grid", gap: 2 }}>
                      <div style={{ fontSize: 17, fontWeight: 600 }}>{selectedStudent.display_name}</div>
                      <div style={{ fontSize: 12, color: D.muted }}>{selectedStudent.email}</div>
                      <div style={{ fontSize: 11, color: D.dim }}>
                        {selectedStudent.role_in_section} · {selectedStudent.membership_status}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 12,
                    }}
                  >
                    <Stat
                      label="// total_sessions"
                      value={selectedStudent.session_count}
                      sub="all time"
                    />
                    <Stat
                      label="// membership"
                      value={selectedStudent.membership_status}
                      sub="Aurora status"
                      color={D.blue}
                    />
                    <Stat
                      label="// last_session"
                      value={selectedStudent.last_session_at ? "recent" : "none"}
                      sub={formatLastSession(selectedStudent.last_session_at)}
                      color={selectedStudent.last_session_at ? D.green : D.muted}
                    />
                  </div>
                </Card>
              ) : null}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {loadingStudents && <div style={{ fontSize: 12, color: D.muted }}>Loading roster...</div>}
                {!loadingStudents && students.length === 0 && (
                  <div style={{ fontSize: 12, color: D.dim }}>No students found for this section.</div>
                )}
                {students.map((student) => (
                  <Card
                    key={student.user_id}
                    onClick={() => setSelectedStudentId(student.user_id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      borderColor: student.user_id === selectedStudentId ? D.orangeBorder : D.border,
                      background: student.user_id === selectedStudentId ? D.orangeGlow : D.card,
                    }}
                  >
                    <Avatar name={student.display_name || student.email} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{student.display_name}</div>
                      <div style={{ fontSize: 11, color: D.muted }}>{student.email}</div>
                    </div>
                    <Tag color={D.green}>{student.session_count} sessions</Tag>
                    <Tag color={D.blue}>{student.membership_status}</Tag>
                  </Card>
                ))}
              </div>
            </div>
          ) : tab === "analytics" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                Section analytics <Tag color={D.muted}>STUB</Tag>
              </div>
              <Card style={{ marginBottom: 12, fontSize: 12, color: D.muted }}>
                Analytics cards remain stubbed until the aggregation API lands. The roster and section
                selector above are live.
              </Card>
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
