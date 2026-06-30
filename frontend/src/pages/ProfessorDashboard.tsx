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
import { Avatar, Btn, Card, Stat, Tag } from "../design/atoms";
import { chartTooltipStyle, D, mono } from "../design/tokens";
import { Sidebar } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";
import {
  defaultWeekLaunchConfigs,
  getWeekLaunchUrl,
  isWeekLaunchReady,
  loadWeekLaunchConfigs,
  saveWeekLaunchConfigs,
  type WeekLaunchConfig,
} from "../data/codespaces";

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
  { key: "materials", icon: "📚", label: "Materials" },
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
  const [weeks, setWeeks] = useState<WeekLaunchConfig[]>(() => loadWeekLaunchConfigs());
  const [sections, setSections] = useState<ProfessorSectionSummary[]>([]);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [students, setStudents] = useState<ProfessorSectionStudent[]>([]);
  const [loadingSections, setLoadingSections] = useState(true);
  const [studentFetchComplete, setStudentFetchComplete] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [studentError, setStudentError] = useState<string | null>(null);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);

  const enabledWeeks = useMemo(() => weeks.filter((week) => week.enabled), [weeks]);
  const selectedSection = useMemo(
    () => sections.find((section) => section.section_id === selectedSectionId) ?? null,
    [sections, selectedSectionId]
  );
  const selectedStudent = useMemo(
    () => students.find((student) => student.user_id === selectedStudentId) ?? null,
    [selectedStudentId, students]
  );
  const loadingStudents = Boolean(selectedSectionId) && !studentFetchComplete && !studentError;

  useEffect(() => {
    saveWeekLaunchConfigs(weeks);
  }, [weeks]);

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

  const updateWeek = (id: string, patch: Partial<WeekLaunchConfig>) => {
    setWeeks((current) =>
      current.map((week) => (week.id === id ? { ...week, ...patch } : week))
    );
  };

  const resetWeeks = () => {
    setWeeks(defaultWeekLaunchConfigs.map((week) => ({ ...week })));
  };

  const handleSectionChange = (nextSectionId: string | null) => {
    setSelectedSectionId(nextSectionId);
    setStudents([]);
    setSelectedStudentId(null);
    setStudentError(null);
    setStudentFetchComplete(false);
  };

  const rosterSummary = selectedSection
    ? `${selectedSection.student_count} students · ${selectedSection.ta_count} TAs · ${selectedSection.professor_count} professors`
    : "Select a section to view the roster";

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
        <span style={{ fontSize: 13, color: D.muted }}>Teaching:</span>
        <select
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
        <Tag color={D.muted}>Live roster</Tag>
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
                {selectedSection ? selectedSection.display_name : "Professor overview"}
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
                  Week repo routing <Tag color={D.muted}>Local config</Tag>
                </div>
                <Btn small variant="ghost" onClick={resetWeeks}>
                  Reset defaults
                </Btn>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {weeks.map((week, index) => (
                  <Card key={week.id} style={{ display: "grid", gap: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>
                        Week {index + 1} settings
                      </div>
                      <Tag color={week.enabled ? D.green : D.muted}>
                        {week.enabled ? "Enabled" : "Disabled"}
                      </Tag>
                    </div>

                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>Week label</span>
                      <input
                        value={week.label}
                        onChange={(event) => updateWeek(week.id, { label: event.target.value })}
                        style={inputStyle}
                      />
                    </label>

                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Student repo URL for this week
                      </span>
                      <input
                        value={week.repoUrl}
                        onChange={(event) => updateWeek(week.id, { repoUrl: event.target.value })}
                        style={inputStyle}
                      />
                    </label>

                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Codespaces template URL for this week
                      </span>
                      <input
                        value={week.templateUrl}
                        onChange={(event) =>
                          updateWeek(week.id, { templateUrl: event.target.value })
                        }
                        style={inputStyle}
                      />
                    </label>

                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Default branch for Codespaces
                      </span>
                      <input
                        value={week.defaultBranch}
                        onChange={(event) =>
                          updateWeek(week.id, { defaultBranch: event.target.value })
                        }
                        style={inputStyle}
                      />
                    </label>

                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 13,
                        color: D.text,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={week.enabled}
                        onChange={(event) => updateWeek(week.id, { enabled: event.target.checked })}
                      />
                      Enable this week for students
                    </label>

                    <div style={{ fontSize: 11, color: D.muted }}>
                      Students will see this week in the launcher when it is enabled.
                      Launch target: <code>{getWeekLaunchUrl(week)}</code>
                    </div>

                    <div style={{ fontSize: 11, color: D.muted }}>
                      Status: {isWeekLaunchReady(week) ? "launch ready" : "missing repo/template URL"}
                    </div>
                  </Card>
                ))}
              </div>
              <div style={{ marginTop: 12, fontSize: 12, color: D.muted }}>
                Enabled weeks: {enabledWeeks.map((week) => week.label).join(", ") || "none"}
              </div>
            </div>
          ) : tab === "students" ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ fontSize: 18, fontWeight: 600 }}>
                Students for {selectedSection ? selectedSection.display_name : "selected section"}{" "}
                <Tag color={D.muted}>{loadingStudents ? "loading" : "live"}</Tag>
              </div>
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
                Class analytics <Tag color={D.muted}>STUB</Tag>
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
