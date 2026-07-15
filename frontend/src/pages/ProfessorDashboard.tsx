import { useEffect, useMemo, useState } from "react";
import {
  inviteProfessorSectionStudent,
  getProfessorSectionAnalytics,
  getProfessorSectionStudentAnalytics,
  getProfessorSectionStudentFeedback,
  listProfessorSectionStudents,
  listProfessorSections,
  type ProfessorSectionStudentInvitePayload,
  type ProfessorSectionAnalytics,
  type ProfessorSectionStudentAnalytics,
  type ProfessorStudentFeedbackResponse,
  type ProfessorSectionStudent,
  type ProfessorSectionSummary,
} from "../api/professorSectionsApi";
import {
  listProfessorSectionLaunchConfigs,
  replaceProfessorSectionLaunchConfigs,
  type SectionLaunchConfig,
} from "../api/sectionLaunchConfigsApi";
import {
  archiveProfessorTeachingPlan,
  createProfessorTeachingPlanWeek,
  deleteProfessorTeachingPlanWeek,
  getProfessorTeachingPlan,
  publishProfessorTeachingPlan,
  saveProfessorTeachingPlan,
  updateProfessorTeachingPlanWeek,
  type ProfessorTeachingPlan,
  type ProfessorTeachingPlanWeek,
} from "../api/teachingPlanApi";
import {
  getProfessorSectionInstructionSettings,
  updateProfessorSectionInstructionSettings,
  type SectionInstructionSettings,
  type SectionWeekVisibilityStatus,
  type SectionWeekResolutionMode,
} from "../api/sectionInstructionSettingsApi";
import { Avatar, Btn, Card, Stat, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import { Sidebar } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import { TeachingPlanWeekReferencesEditor } from "../components/professor/TeachingPlanWeekReferencesEditor";
import { ProfessorAnalyticsCharts } from "../components/professor/ProfessorAnalyticsCharts";
import { ProfessorStudentFeedback } from "../components/professor/ProfessorStudentFeedback";
import type { AppView } from "../types/navigation";
import { getWeekLaunchUrl, isWeekLaunchReady } from "../data/codespaces";

interface ProfessorDashboardProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
  accessToken: string;
}

const profTabs = [
  { key: "overview", icon: "📋", label: "Overview" },
  { key: "launches", icon: "🚀", label: "Launches" },
  { key: "teaching-plan", icon: "🧭", label: "Teaching Plan" },
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

function nextTeachingPlanWeekNumber(
  plan: ProfessorTeachingPlan | null,
): number {
  const highestWeek =
    plan?.weeks.reduce((max, week) => Math.max(max, week.week_number), 0) ?? 0;
  return highestWeek + 1;
}

function splitObjectives(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function dateInputValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  return value.slice(0, 10);
}

export function ProfessorDashboard({
  onNavigate,
  allowedViews,
  onSignOut,
  accessToken,
}: ProfessorDashboardProps) {
  const [tab, setTab] = useState("overview");
  const [sections, setSections] = useState<ProfessorSectionSummary[]>([]);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(
    null,
  );
  const [students, setStudents] = useState<ProfessorSectionStudent[]>([]);
  const [analytics, setAnalytics] = useState<ProfessorSectionAnalytics | null>(
    null,
  );
  const [analyticsSectionId, setAnalyticsSectionId] = useState<string | null>(
    null,
  );
  const [studentAnalytics, setStudentAnalytics] =
    useState<ProfessorSectionStudentAnalytics | null>(null);
  const [studentAnalyticsSectionId, setStudentAnalyticsSectionId] = useState<
    string | null
  >(null);
  const [studentAnalyticsStudentId, setStudentAnalyticsStudentId] = useState<
    string | null
  >(null);
  const [launchConfigs, setLaunchConfigs] = useState<SectionLaunchConfig[]>([]);
  const [launchConfigsSectionId, setLaunchConfigsSectionId] = useState<
    string | null
  >(null);
  const [teachingPlan, setTeachingPlan] =
    useState<ProfessorTeachingPlan | null>(null);
  const [teachingPlanSectionId, setTeachingPlanSectionId] = useState<
    string | null
  >(null);
  const [sectionSettings, setSectionSettings] =
    useState<SectionInstructionSettings | null>(null);
  const [sectionSettingsSectionId, setSectionSettingsSectionId] = useState<
    string | null
  >(null);
  const [loadingSections, setLoadingSections] = useState(true);
  const [studentFetchComplete, setStudentFetchComplete] = useState(false);
  const [analyticsFetchComplete, setAnalyticsFetchComplete] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [studentError, setStudentError] = useState<string | null>(null);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [studentAnalyticsError, setStudentAnalyticsError] = useState<
    string | null
  >(null);
  const [studentFeedback, setStudentFeedback] =
    useState<ProfessorStudentFeedbackResponse | null>(null);
  const [studentFeedbackError, setStudentFeedbackError] = useState<
    string | null
  >(null);
  const [studentDrillDownTab, setStudentDrillDownTab] = useState<
    "analytics" | "feedback"
  >("analytics");
  const [launchConfigError, setLaunchConfigError] = useState<string | null>(
    null,
  );
  const [launchConfigStatus, setLaunchConfigStatus] = useState<string | null>(
    null,
  );
  const [teachingPlanError, setTeachingPlanError] = useState<string | null>(
    null,
  );
  const [teachingPlanStatus, setTeachingPlanStatus] = useState<string | null>(
    null,
  );
  const [sectionSettingsError, setSectionSettingsError] = useState<
    string | null
  >(null);
  const [sectionSettingsStatus, setSectionSettingsStatus] = useState<
    string | null
  >(null);
  const [savingLaunchConfigs, setSavingLaunchConfigs] = useState(false);
  const [savingTeachingPlan, setSavingTeachingPlan] = useState(false);
  const [savingTeachingPlanWeekId, setSavingTeachingPlanWeekId] = useState<
    string | null
  >(null);
  const [savingSectionSettings, setSavingSectionSettings] = useState(false);
  const [creatingTeachingPlanWeek, setCreatingTeachingPlanWeek] =
    useState(false);
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(
    null,
  );
  const [inviteStudentEmail, setInviteStudentEmail] = useState("");
  const [inviteStudentDisplayName, setInviteStudentDisplayName] = useState("");
  const [invitingStudent, setInvitingStudent] = useState(false);
  const [inviteStudentError, setInviteStudentError] = useState<string | null>(
    null,
  );
  const [inviteStudentStatus, setInviteStudentStatus] = useState<string | null>(
    null,
  );
  const selectedSection = useMemo(
    () =>
      sections.find((section) => section.section_id === selectedSectionId) ??
      null,
    [sections, selectedSectionId],
  );
  const selectedStudent = useMemo(
    () =>
      students.find((student) => student.user_id === selectedStudentId) ?? null,
    [selectedStudentId, students],
  );
  const activeLaunchConfigs = useMemo(
    () => (launchConfigsSectionId === selectedSectionId ? launchConfigs : []),
    [launchConfigs, launchConfigsSectionId, selectedSectionId],
  );
  const activeAnalytics = useMemo(
    () => (analyticsSectionId === selectedSectionId ? analytics : null),
    [analytics, analyticsSectionId, selectedSectionId],
  );
  const activeStudentAnalytics = useMemo(
    () =>
      studentAnalyticsSectionId === selectedSectionId &&
      studentAnalyticsStudentId === selectedStudentId
        ? studentAnalytics
        : null,
    [
      selectedSectionId,
      selectedStudentId,
      studentAnalytics,
      studentAnalyticsSectionId,
      studentAnalyticsStudentId,
    ],
  );
  const activeTeachingPlan = useMemo(
    () => (teachingPlanSectionId === selectedSectionId ? teachingPlan : null),
    [selectedSectionId, teachingPlan, teachingPlanSectionId],
  );
  const activeSectionSettings = useMemo(
    () =>
      sectionSettingsSectionId === selectedSectionId ? sectionSettings : null,
    [sectionSettings, sectionSettingsSectionId, selectedSectionId],
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
    !launchConfigError,
  );
  const loadingAnalytics =
    Boolean(selectedSectionId) && !analyticsFetchComplete && !analyticsError;
  const loadingStudentAnalytics =
    Boolean(selectedSectionId && selectedStudentId) &&
    (studentAnalyticsSectionId !== selectedSectionId ||
      studentAnalyticsStudentId !== selectedStudentId);
  const loadingTeachingPlan = Boolean(
    selectedSectionId &&
    accessToken &&
    teachingPlanSectionId !== selectedSectionId &&
    !teachingPlanError,
  );
  const loadingSectionSettings = Boolean(
    selectedSectionId &&
    accessToken &&
    sectionSettingsSectionId !== selectedSectionId &&
    !sectionSettingsError,
  );
  const loadingStudents =
    Boolean(selectedSectionId) && !studentFetchComplete && !studentError;

  useEffect(() => {
    let cancelled = false;

    void listProfessorSections(accessToken)
      .then((nextSections) => {
        if (cancelled) return;
        setSections(nextSections);
        setSelectedSectionId(
          (current) => current ?? nextSections[0]?.section_id ?? null,
        );
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
    if (!selectedSectionId || !accessToken) {
      return;
    }

    let cancelled = false;

    void getProfessorSectionInstructionSettings(selectedSectionId, accessToken)
      .then((nextSettings) => {
        if (cancelled) return;
        setSectionSettings(nextSettings);
        setSectionSettingsSectionId(selectedSectionId);
        setSectionSettingsStatus(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setSectionSettings(null);
          setSectionSettingsSectionId(selectedSectionId);
          setSectionSettingsError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId]);

  useEffect(() => {
    if (!selectedSectionId || !accessToken) {
      return;
    }

    let cancelled = false;

    void getProfessorTeachingPlan(selectedSectionId, accessToken)
      .then((nextPlan) => {
        if (cancelled) return;
        setTeachingPlan(nextPlan);
        setTeachingPlanSectionId(selectedSectionId);
        setTeachingPlanStatus(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setTeachingPlan(null);
          setTeachingPlanSectionId(selectedSectionId);
          setTeachingPlanError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId]);

  useEffect(() => {
    if (!selectedSectionId || !accessToken) {
      return;
    }

    let cancelled = false;

    void getProfessorSectionAnalytics(selectedSectionId, accessToken)
      .then((nextAnalytics) => {
        if (cancelled) return;
        setAnalytics(nextAnalytics);
        setAnalyticsSectionId(selectedSectionId);
        setAnalyticsError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setAnalytics(null);
          setAnalyticsSectionId(selectedSectionId);
          setAnalyticsError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setAnalyticsFetchComplete(true);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId]);

  useEffect(() => {
    if (
      tab !== "analytics" ||
      !selectedSectionId ||
      !selectedStudentId ||
      !accessToken
    ) {
      return;
    }

    let cancelled = false;

    Promise.all([
      getProfessorSectionStudentAnalytics(
        selectedSectionId,
        selectedStudentId,
        accessToken,
      ),
      getProfessorSectionStudentFeedback(
        selectedSectionId,
        selectedStudentId,
        accessToken,
      ),
    ])
      .then(([nextAnalytics, nextFeedback]) => {
        if (cancelled) return;
        setStudentAnalytics(nextAnalytics);
        setStudentFeedback(nextFeedback);
        setStudentAnalyticsSectionId(selectedSectionId);
        setStudentAnalyticsStudentId(selectedStudentId);
        setStudentAnalyticsError(null);
        setStudentFeedbackError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setStudentAnalytics(null);
          setStudentFeedback(null);
          setStudentAnalyticsSectionId(selectedSectionId);
          setStudentAnalyticsStudentId(selectedStudentId);
          setStudentAnalyticsError(err.message);
          setStudentFeedbackError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedSectionId, selectedStudentId, tab]);

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
    setStudentAnalytics(null);
    setStudentAnalyticsSectionId(null);
    setStudentAnalyticsStudentId(null);
    setStudentAnalyticsError(null);
    setInviteStudentEmail("");
    setInviteStudentDisplayName("");
    setInvitingStudent(false);
    setInviteStudentError(null);
    setInviteStudentStatus(null);
    setAnalytics(null);
    setAnalyticsSectionId(null);
    setAnalyticsError(null);
    setAnalyticsFetchComplete(false);
    setLaunchConfigError(null);
    setLaunchConfigStatus(null);
    setTeachingPlan(null);
    setTeachingPlanSectionId(null);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);
    setSectionSettings(null);
    setSectionSettingsSectionId(null);
    setSectionSettingsError(null);
    setSectionSettingsStatus(null);
  };

  const rosterSummary = selectedSection
    ? `${selectedSection.student_count} students · ${selectedSection.ta_count} TAs · ${selectedSection.professor_count} professors`
    : "Select a section to view the roster";

  const updateLaunchConfig = (
    launchId: string,
    patch: Partial<SectionLaunchConfig>,
  ) => {
    setLaunchConfigs((current) =>
      current.map((config) =>
        config.launch_id === launchId ? { ...config, ...patch } : config,
      ),
    );
  };

  const addLaunchConfig = () => {
    setLaunchConfigs((current) => [
      ...current,
      emptyLaunchConfig(current.length),
    ]);
  };

  const removeLaunchConfig = (launchId: string) => {
    setLaunchConfigs((current) =>
      current.filter((config) => config.launch_id !== launchId),
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
        cleaned,
      );
      setLaunchConfigs(updated);
      setLaunchConfigsSectionId(selectedSectionId);
      setLaunchConfigStatus("Saved launch configs.");
    } catch (err) {
      setLaunchConfigError(
        err instanceof Error ? err.message : "Unable to save launch configs.",
      );
    } finally {
      setSavingLaunchConfigs(false);
    }
  };

  const reloadTeachingPlan = () => {
    if (!selectedSectionId) {
      return;
    }
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);
    setTeachingPlanSectionId(null);
    void getProfessorTeachingPlan(selectedSectionId, accessToken)
      .then((nextPlan) => {
        setTeachingPlan(nextPlan);
        setTeachingPlanSectionId(selectedSectionId);
      })
      .catch((err: Error) => {
        setTeachingPlan(null);
        setTeachingPlanSectionId(selectedSectionId);
        setTeachingPlanError(err.message);
      });
  };

  const saveTeachingPlan = async () => {
    if (!selectedSectionId || !activeTeachingPlan) {
      return;
    }

    setSavingTeachingPlan(true);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const updated = await saveProfessorTeachingPlan(
        selectedSectionId,
        accessToken,
        {
          title: activeTeachingPlan.title.trim(),
          summary: activeTeachingPlan.summary.trim(),
        },
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus("Saved teaching plan.");
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error ? err.message : "Unable to save teaching plan.",
      );
    } finally {
      setSavingTeachingPlan(false);
    }
  };

  const publishTeachingPlan = async () => {
    if (!selectedSectionId) {
      return;
    }

    setSavingTeachingPlan(true);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const updated = await publishProfessorTeachingPlan(
        selectedSectionId,
        accessToken,
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus("Published teaching plan.");
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error ? err.message : "Unable to publish teaching plan.",
      );
    } finally {
      setSavingTeachingPlan(false);
    }
  };

  const archiveTeachingPlan = async () => {
    if (!selectedSectionId) {
      return;
    }

    setSavingTeachingPlan(true);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const updated = await archiveProfessorTeachingPlan(
        selectedSectionId,
        accessToken,
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus("Archived teaching plan.");
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error ? err.message : "Unable to archive teaching plan.",
      );
    } finally {
      setSavingTeachingPlan(false);
    }
  };

  const createTeachingPlanWeek = async () => {
    if (!selectedSectionId) {
      return;
    }

    setCreatingTeachingPlanWeek(true);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const nextWeekNumber = nextTeachingPlanWeekNumber(activeTeachingPlan);
      const updated = await createProfessorTeachingPlanWeek(
        selectedSectionId,
        accessToken,
        {
          week_number: nextWeekNumber,
          title: `Week ${nextWeekNumber}`,
          topic: "",
          learning_objectives: [],
          instructional_guidance: "",
          status: "draft",
          student_visibility_status: "hidden",
          available_from: null,
          available_until: null,
        },
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus(`Added week ${nextWeekNumber}.`);
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error
          ? err.message
          : "Unable to add teaching plan week.",
      );
    } finally {
      setCreatingTeachingPlanWeek(false);
    }
  };

  const saveTeachingPlanWeek = async (week: ProfessorTeachingPlanWeek) => {
    if (!selectedSectionId) {
      return;
    }

    setSavingTeachingPlanWeekId(week.week_id);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const updated = await updateProfessorTeachingPlanWeek(
        selectedSectionId,
        week.week_id,
        accessToken,
        {
          week_number: week.week_number,
          title: week.title,
          topic: week.topic,
          start_date: week.start_date,
          end_date: week.end_date,
          learning_objectives: week.learning_objectives,
          instructional_guidance: week.instructional_guidance,
          status: week.status,
          student_visibility_status: week.student_visibility_status,
          available_from: week.available_from,
          available_until: week.available_until,
        },
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus(`Saved week ${week.week_number}.`);
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error
          ? err.message
          : "Unable to save teaching plan week.",
      );
    } finally {
      setSavingTeachingPlanWeekId(null);
    }
  };

  const deleteTeachingPlanWeek = async (week: ProfessorTeachingPlanWeek) => {
    if (!selectedSectionId) {
      return;
    }

    setSavingTeachingPlanWeekId(week.week_id);
    setTeachingPlanError(null);
    setTeachingPlanStatus(null);

    try {
      const updated = await deleteProfessorTeachingPlanWeek(
        selectedSectionId,
        week.week_id,
        accessToken,
      );
      setTeachingPlan(updated);
      setTeachingPlanSectionId(selectedSectionId);
      setTeachingPlanStatus(`Deleted week ${week.week_number}.`);
    } catch (err) {
      setTeachingPlanError(
        err instanceof Error
          ? err.message
          : "Unable to delete teaching plan week.",
      );
    } finally {
      setSavingTeachingPlanWeekId(null);
    }
  };

  const updateTeachingPlanWeekDraft = (
    weekId: string,
    patch: Partial<ProfessorTeachingPlanWeek>,
  ) => {
    setTeachingPlan((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        weeks: current.weeks.map((week) =>
          week.week_id === weekId ? { ...week, ...patch } : week,
        ),
      };
    });
  };

  const replaceTeachingPlanWeek = (nextWeek: ProfessorTeachingPlanWeek) => {
    setTeachingPlan((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        weeks: current.weeks.map((week) =>
          week.week_id === nextWeek.week_id ? nextWeek : week,
        ),
      };
    });
  };

  const updateSectionSettingsDraft = (
    patch: Partial<SectionInstructionSettings>,
  ) => {
    setSectionSettings((current) => {
      if (!current) {
        return current;
      }
      return { ...current, ...patch };
    });
  };

  const saveSectionSettings = async () => {
    if (!selectedSectionId || !activeSectionSettings) {
      return;
    }

    setSavingSectionSettings(true);
    setSectionSettingsError(null);
    setSectionSettingsStatus(null);

    try {
      const updated = await updateProfessorSectionInstructionSettings(
        selectedSectionId,
        accessToken,
        {
          student_access_enabled: activeSectionSettings.student_access_enabled,
          week_resolution_mode: activeSectionSettings.week_resolution_mode,
          manual_current_week_number:
            activeSectionSettings.manual_current_week_number,
          teaching_plan_prompt_enabled:
            activeSectionSettings.teaching_plan_prompt_enabled,
          references_prompt_enabled:
            activeSectionSettings.references_prompt_enabled,
          references_retrieval_enabled:
            activeSectionSettings.references_retrieval_enabled,
        },
      );
      setSectionSettings(updated);
      setSectionSettingsSectionId(selectedSectionId);
      setSectionSettingsStatus("Saved section instruction settings.");
    } catch (err) {
      setSectionSettingsError(
        err instanceof Error
          ? err.message
          : "Unable to save section instruction settings.",
      );
    } finally {
      setSavingSectionSettings(false);
    }
  };

  const inviteStudent = async () => {
    if (!selectedSectionId || !inviteStudentEmail.trim()) {
      return;
    }

    setInvitingStudent(true);
    setInviteStudentError(null);
    setInviteStudentStatus(null);

    const payload: ProfessorSectionStudentInvitePayload = {
      email: inviteStudentEmail.trim(),
      display_name: inviteStudentDisplayName.trim(),
    };

    try {
      const nextStudents = await inviteProfessorSectionStudent(
        selectedSectionId,
        accessToken,
        payload,
      );
      setStudents(nextStudents);
      const invitedStudent = nextStudents.find(
        (student) =>
          student.email.toLowerCase() === payload.email.toLowerCase(),
      );
      setSelectedStudentId(
        invitedStudent?.user_id ?? nextStudents[0]?.user_id ?? null,
      );
      setInviteStudentEmail("");
      setInviteStudentDisplayName("");
      setInviteStudentStatus(`Invitation saved for ${payload.email}.`);
    } catch (err) {
      setInviteStudentError(
        err instanceof Error ? err.message : "Unable to invite student.",
      );
    } finally {
      setInvitingStudent(false);
    }
  };

  const openStudentAnalytics = (studentUserId: string) => {
    setSelectedStudentId(studentUserId);
    setTab("analytics");
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
          {!loadingSections && sections.length === 0 && (
            <option value="">No sections found</option>
          )}
          {sections.map((section) => (
            <option key={section.section_id} value={section.section_id}>
              {section.section_id} · {section.display_name}
            </option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        <Tag color={D.green}>
          {selectedSection ? selectedSection.course_id : "no section"}
        </Tag>
        <Tag color={D.red}>
          {selectedSection
            ? `${selectedSection.student_count} students`
            : "no roster"}
        </Tag>
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
                {selectedSection
                  ? selectedSection.display_name
                  : "Section overview"}
              </div>
              {sectionError && (
                <Card style={{ marginBottom: 14, color: D.red, fontSize: 12 }}>
                  {sectionError}
                </Card>
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
                <div style={{ fontSize: 12, color: D.muted }}>
                  Section context
                </div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>
                  {selectedSection
                    ? selectedSection.section_id
                    : "No section selected"}
                </div>
                <div style={{ fontSize: 12, color: D.dim }}>
                  {selectedSection
                    ? `${selectedSection.course_id} · ${selectedSection.course_display_name} · ${selectedSection.term || "n/a"}`
                    : "Choose a section from the selector above."}
                </div>
                <div style={{ fontSize: 12, color: D.dim, lineHeight: 1.5 }}>
                  Students use the launch configs in this section to enter the
                  workspace. Keep the selected section and its launch setup
                  aligned with the roster below.
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Tag color={selectedSection?.is_active ? D.green : D.red}>
                    {selectedSection?.is_active
                      ? "active section"
                      : "inactive section"}
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
              <Card style={{ display: "grid", gap: 12 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div>
                    <div
                      style={{ fontSize: 12, color: D.muted, marginBottom: 6 }}
                    >
                      Section controls
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>
                      {selectedSection
                        ? selectedSection.section_id
                        : "No section selected"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <Tag
                      color={
                        activeSectionSettings?.student_access_enabled
                          ? D.green
                          : D.red
                      }
                    >
                      {activeSectionSettings?.student_access_enabled
                        ? "open to students"
                        : "student access paused"}
                    </Tag>
                    <Tag color={D.blue}>
                      {activeSectionSettings?.week_resolution_mode ?? "manual"}
                    </Tag>
                    <Tag color={D.orange}>
                      week{" "}
                      {activeSectionSettings?.manual_current_week_number
                        ? activeSectionSettings.manual_current_week_number
                        : "unset"}
                    </Tag>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: D.dim, lineHeight: 1.6 }}>
                  These settings control when students can use this section and
                  which professor instructional signals are considered active.
                </div>
                {sectionSettingsError && (
                  <Card style={{ color: D.red, fontSize: 12 }}>
                    {sectionSettingsError}
                  </Card>
                )}
                {sectionSettingsStatus && (
                  <Card style={{ color: D.green, fontSize: 12 }}>
                    {sectionSettingsStatus}
                  </Card>
                )}
                {loadingSectionSettings ? (
                  <div style={{ fontSize: 12, color: D.muted }}>
                    Loading section controls...
                  </div>
                ) : (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 12,
                    }}
                  >
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Student access
                      </span>
                      <label
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          fontSize: 13,
                        }}
                      >
                        <input
                          type="checkbox"
                          aria-label="Open to students"
                          checked={
                            activeSectionSettings?.student_access_enabled ??
                            true
                          }
                          onChange={(event) =>
                            updateSectionSettingsDraft({
                              student_access_enabled: event.target.checked,
                            })
                          }
                        />
                        Open to students
                      </label>
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Week resolution mode
                      </span>
                      <select
                        value={
                          activeSectionSettings?.week_resolution_mode ??
                          "manual"
                        }
                        onChange={(event) =>
                          updateSectionSettingsDraft({
                            week_resolution_mode: event.target
                              .value as SectionWeekResolutionMode,
                          })
                        }
                        style={inputStyle}
                      >
                        <option value="manual">Manual</option>
                        <option value="date_driven">Date driven</option>
                      </select>
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Manual current week
                      </span>
                      <input
                        type="number"
                        min={1}
                        value={
                          activeSectionSettings?.manual_current_week_number ??
                          ""
                        }
                        onChange={(event) =>
                          updateSectionSettingsDraft({
                            manual_current_week_number: event.target.value
                              ? Number(event.target.value)
                              : null,
                          })
                        }
                        style={inputStyle}
                      />
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        Teaching plan prompt context
                      </span>
                      <label
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          fontSize: 13,
                        }}
                      >
                        <input
                          type="checkbox"
                          aria-label="Include published plan in prompt"
                          checked={
                            activeSectionSettings?.teaching_plan_prompt_enabled ??
                            false
                          }
                          onChange={(event) =>
                            updateSectionSettingsDraft({
                              teaching_plan_prompt_enabled:
                                event.target.checked,
                            })
                          }
                        />
                        Include published plan in prompt
                      </label>
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        References prompt context
                      </span>
                      <label
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          fontSize: 13,
                        }}
                      >
                        <input
                          type="checkbox"
                          aria-label="Include section references in prompt"
                          checked={
                            activeSectionSettings?.references_prompt_enabled ??
                            false
                          }
                          onChange={(event) =>
                            updateSectionSettingsDraft({
                              references_prompt_enabled: event.target.checked,
                            })
                          }
                        />
                        Include section references in prompt
                      </label>
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={{ fontSize: 12, color: D.muted }}>
                        References retrieval context
                      </span>
                      <label
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          fontSize: 13,
                        }}
                      >
                        <input
                          type="checkbox"
                          aria-label="Allow references in retrieval"
                          checked={
                            activeSectionSettings?.references_retrieval_enabled ??
                            false
                          }
                          onChange={(event) =>
                            updateSectionSettingsDraft({
                              references_retrieval_enabled:
                                event.target.checked,
                            })
                          }
                        />
                        Allow references in retrieval
                      </label>
                    </label>
                  </div>
                )}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    gap: 8,
                  }}
                >
                  <Btn
                    small
                    onClick={() => void saveSectionSettings()}
                    disabled={
                      !selectedSectionId ||
                      savingSectionSettings ||
                      loadingSectionSettings
                    }
                  >
                    {savingSectionSettings ? "Saving..." : "Save controls"}
                  </Btn>
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
                  <Btn
                    small
                    variant="ghost"
                    onClick={addLaunchConfig}
                    disabled={!selectedSectionId}
                  >
                    Add launch option
                  </Btn>
                  <Btn
                    small
                    variant="ghost"
                    onClick={resetLaunchConfigs}
                    disabled={!selectedSectionId}
                  >
                    Reload
                  </Btn>
                  <Btn
                    small
                    onClick={() => void saveLaunchConfigs()}
                    disabled={
                      !selectedSectionId ||
                      savingLaunchConfigs ||
                      loadingLaunchConfigs
                    }
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
                <Card
                  style={{ marginBottom: 12, color: D.green, fontSize: 12 }}
                >
                  {launchConfigStatus}
                </Card>
              )}
              {loadingLaunchConfigs ? (
                <Card>Loading launch configs...</Card>
              ) : (
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 10 }}
                >
                  {activeLaunchConfigs.length === 0 && (
                    <Card
                      style={{ color: D.muted, fontSize: 13, lineHeight: 1.7 }}
                    >
                      No launch configs are saved for this section yet. Add one
                      to define the Codespaces launch target students should
                      use.
                    </Card>
                  )}
                  {activeLaunchConfigs.map((launchConfig, index) => (
                    <Card
                      key={launchConfig.launch_id}
                      style={{ display: "grid", gap: 10 }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                        }}
                      >
                        <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>
                          Launch option {index + 1}
                        </div>
                        <Tag color={launchConfig.enabled ? D.green : D.muted}>
                          {launchConfig.enabled ? "Enabled" : "Disabled"}
                        </Tag>
                        <Btn
                          small
                          variant="danger"
                          onClick={() =>
                            removeLaunchConfig(launchConfig.launch_id)
                          }
                        >
                          Remove
                        </Btn>
                      </div>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Launch ID
                        </span>
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
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Label
                        </span>
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

                      <div
                        style={{ display: "flex", gap: 16, flexWrap: "wrap" }}
                      >
                        <label
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            fontSize: 12,
                            color: D.muted,
                          }}
                        >
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
                          <code>
                            {getWeekLaunchUrl(toWeekLaunchConfig(launchConfig))}
                          </code>
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
          ) : tab === "teaching-plan" ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <div style={{ fontSize: 18, fontWeight: 600 }}>
                  Teaching Plan for{" "}
                  {selectedSection
                    ? selectedSection.display_name
                    : "selected section"}{" "}
                  <Tag
                    color={
                      activeTeachingPlan?.status === "published"
                        ? D.green
                        : D.blue
                    }
                  >
                    {activeTeachingPlan?.status || "draft"}
                  </Tag>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Btn
                    small
                    variant="ghost"
                    onClick={reloadTeachingPlan}
                    disabled={!selectedSectionId}
                  >
                    Reload
                  </Btn>
                  <Btn
                    small
                    variant="ghost"
                    onClick={() => void createTeachingPlanWeek()}
                    disabled={!selectedSectionId || creatingTeachingPlanWeek}
                  >
                    {creatingTeachingPlanWeek ? "Adding..." : "Add week"}
                  </Btn>
                  <Btn
                    small
                    variant="ghost"
                    onClick={() => void archiveTeachingPlan()}
                    disabled={!selectedSectionId || savingTeachingPlan}
                  >
                    Archive
                  </Btn>
                  <Btn
                    small
                    onClick={() => void saveTeachingPlan()}
                    disabled={
                      !selectedSectionId ||
                      savingTeachingPlan ||
                      loadingTeachingPlan
                    }
                  >
                    {savingTeachingPlan ? "Saving..." : "Save plan"}
                  </Btn>
                  <Btn
                    small
                    onClick={() => void publishTeachingPlan()}
                    disabled={
                      !selectedSectionId ||
                      savingTeachingPlan ||
                      loadingTeachingPlan
                    }
                  >
                    Publish
                  </Btn>
                </div>
              </div>
              {teachingPlanError && (
                <Card style={{ color: D.red, fontSize: 12 }}>
                  {teachingPlanError}
                </Card>
              )}
              {teachingPlanStatus && (
                <Card style={{ color: D.green, fontSize: 12 }}>
                  {teachingPlanStatus}
                </Card>
              )}
              <Card style={{ display: "grid", gap: 12 }}>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>
                    Plan title
                  </span>
                  <input
                    value={activeTeachingPlan?.title ?? ""}
                    onChange={(event) =>
                      setTeachingPlan((current) =>
                        current
                          ? { ...current, title: event.target.value }
                          : current,
                      )
                    }
                    style={inputStyle}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>
                    Plan summary
                  </span>
                  <textarea
                    value={activeTeachingPlan?.summary ?? ""}
                    onChange={(event) =>
                      setTeachingPlan((current) =>
                        current
                          ? { ...current, summary: event.target.value }
                          : current,
                      )
                    }
                    rows={4}
                    style={{ ...inputStyle, resize: "vertical", minHeight: 90 }}
                  />
                </label>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Tag color={D.blue}>
                    {activeTeachingPlan?.weeks.length ?? 0} week
                    {(activeTeachingPlan?.weeks.length ?? 0) === 1 ? "" : "s"}
                  </Tag>
                  <Tag color={D.orange}>
                    Version {activeTeachingPlan?.version ?? 1}
                  </Tag>
                  <Tag color={D.muted}>
                    {activeTeachingPlan?.teaching_plan_id
                      ? "saved in Aurora"
                      : "not saved yet"}
                  </Tag>
                </div>
              </Card>
              {loadingTeachingPlan ? (
                <Card>Loading teaching plan...</Card>
              ) : (
                <div style={{ display: "grid", gap: 10 }}>
                  {(activeTeachingPlan?.weeks.length ?? 0) === 0 && (
                    <Card
                      style={{ color: D.muted, fontSize: 13, lineHeight: 1.7 }}
                    >
                      No week plans exist for this section yet. Add the first
                      week to define the instructional scope for students and
                      retrieval.
                    </Card>
                  )}
                  {activeTeachingPlan?.weeks.map((week) => (
                    <Card
                      key={week.week_id}
                      style={{ display: "grid", gap: 10 }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                        }}
                      >
                        <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>
                          Week {week.week_number}
                        </div>
                        <Tag
                          color={
                            week.status === "published" ? D.green : D.muted
                          }
                        >
                          {week.status}
                        </Tag>
                        <Btn
                          small
                          variant="danger"
                          onClick={() => void deleteTeachingPlanWeek(week)}
                          disabled={savingTeachingPlanWeekId === week.week_id}
                        >
                          Delete
                        </Btn>
                      </div>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Week number
                        </span>
                        <input
                          type="number"
                          min={1}
                          value={week.week_number}
                          onChange={(event) =>
                            updateTeachingPlanWeekDraft(week.week_id, {
                              week_number: Number(event.target.value) || 1,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Week title
                        </span>
                        <input
                          value={week.title}
                          onChange={(event) =>
                            updateTeachingPlanWeekDraft(week.week_id, {
                              title: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Topic
                        </span>
                        <input
                          value={week.topic}
                          onChange={(event) =>
                            updateTeachingPlanWeekDraft(week.week_id, {
                              topic: event.target.value,
                            })
                          }
                          style={inputStyle}
                        />
                      </label>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns:
                            "repeat(auto-fit, minmax(180px, 1fr))",
                          gap: 10,
                        }}
                      >
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 12, color: D.muted }}>
                            Start date
                          </span>
                          <input
                            type="date"
                            value={week.start_date ?? ""}
                            onChange={(event) =>
                              updateTeachingPlanWeekDraft(week.week_id, {
                                start_date: event.target.value || null,
                              })
                            }
                            style={inputStyle}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 12, color: D.muted }}>
                            End date
                          </span>
                          <input
                            type="date"
                            value={week.end_date ?? ""}
                            onChange={(event) =>
                              updateTeachingPlanWeekDraft(week.week_id, {
                                end_date: event.target.value || null,
                              })
                            }
                            style={inputStyle}
                          />
                        </label>
                      </div>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Learning objectives, one per line
                        </span>
                        <textarea
                          value={week.learning_objectives.join("\n")}
                          onChange={(event) =>
                            updateTeachingPlanWeekDraft(week.week_id, {
                              learning_objectives: splitObjectives(
                                event.target.value,
                              ),
                            })
                          }
                          rows={4}
                          style={{
                            ...inputStyle,
                            resize: "vertical",
                            minHeight: 100,
                          }}
                        />
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 12, color: D.muted }}>
                          Instructional guidance
                        </span>
                        <textarea
                          value={week.instructional_guidance}
                          onChange={(event) =>
                            updateTeachingPlanWeekDraft(week.week_id, {
                              instructional_guidance: event.target.value,
                            })
                          }
                          rows={4}
                          style={{
                            ...inputStyle,
                            resize: "vertical",
                            minHeight: 100,
                          }}
                        />
                      </label>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns:
                            "repeat(auto-fit, minmax(180px, 1fr))",
                          gap: 10,
                        }}
                      >
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 12, color: D.muted }}>
                            Student visibility status
                          </span>
                          <select
                            value={week.student_visibility_status ?? "hidden"}
                            onChange={(event) =>
                              updateTeachingPlanWeekDraft(week.week_id, {
                                student_visibility_status: event.target
                                  .value as SectionWeekVisibilityStatus,
                              })
                            }
                            style={inputStyle}
                          >
                            <option value="hidden">Hidden</option>
                            <option value="open">Open</option>
                            <option value="closed">Closed</option>
                          </select>
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 12, color: D.muted }}>
                            Available from
                          </span>
                          <input
                            type="date"
                            value={dateInputValue(week.available_from)}
                            onChange={(event) =>
                              updateTeachingPlanWeekDraft(week.week_id, {
                                available_from: event.target.value || null,
                              })
                            }
                            style={inputStyle}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={{ fontSize: 12, color: D.muted }}>
                            Available until
                          </span>
                          <input
                            type="date"
                            value={dateInputValue(week.available_until)}
                            onChange={(event) =>
                              updateTeachingPlanWeekDraft(week.week_id, {
                                available_until: event.target.value || null,
                              })
                            }
                            style={inputStyle}
                          />
                        </label>
                      </div>

                      <TeachingPlanWeekReferencesEditor
                        key={week.week_id}
                        sectionId={selectedSectionId ?? ""}
                        week={week}
                        accessToken={accessToken}
                        onWeekUpdated={replaceTeachingPlanWeek}
                      />

                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 10,
                          flexWrap: "wrap",
                        }}
                      >
                        <div style={{ fontSize: 11, color: D.muted }}>
                          Week ID: <code>{week.week_id}</code>
                        </div>
                        <Btn
                          small
                          onClick={() => void saveTeachingPlanWeek(week)}
                          disabled={savingTeachingPlanWeekId === week.week_id}
                        >
                          {savingTeachingPlanWeekId === week.week_id
                            ? "Saving..."
                            : "Save week"}
                        </Btn>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          ) : tab === "students" ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ fontSize: 18, fontWeight: 600 }}>
                Students for{" "}
                {selectedSection
                  ? selectedSection.display_name
                  : "selected section"}{" "}
                <Tag color={D.muted}>
                  {loadingStudents ? "loading" : "student memberships"}
                </Tag>
              </div>
              <Card style={{ fontSize: 12, color: D.muted, lineHeight: 1.7 }}>
                This roster shows student memberships for the selected section
                and includes live session usage from Aurora-backed telemetry.
                Invites create invited Aurora users that claim their account on
                first login.
              </Card>
              <Card style={{ display: "grid", gap: 12 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  Invite student
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 12,
                  }}
                >
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>
                      Student email
                    </span>
                    <input
                      value={inviteStudentEmail}
                      onChange={(event) =>
                        setInviteStudentEmail(event.target.value)
                      }
                      placeholder="student@example.edu"
                      style={inputStyle}
                    />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>
                      Display name
                    </span>
                    <input
                      value={inviteStudentDisplayName}
                      onChange={(event) =>
                        setInviteStudentDisplayName(event.target.value)
                      }
                      placeholder="Optional"
                      style={inputStyle}
                    />
                  </label>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 10,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ fontSize: 12, color: D.dim, lineHeight: 1.6 }}>
                    Creates or reuses the Aurora application user, then assigns
                    an invited student membership to this section.
                  </div>
                  <Btn
                    small
                    onClick={() => void inviteStudent()}
                    disabled={invitingStudent || !inviteStudentEmail.trim()}
                  >
                    {invitingStudent ? "Inviting..." : "Invite student"}
                  </Btn>
                </div>
                {inviteStudentError && (
                  <div style={{ fontSize: 12, color: D.red }}>
                    {inviteStudentError}
                  </div>
                )}
                {inviteStudentStatus && (
                  <div style={{ fontSize: 12, color: D.green }}>
                    {inviteStudentStatus}
                  </div>
                )}
              </Card>
              {studentError && (
                <Card style={{ color: D.red, fontSize: 12 }}>
                  {studentError}
                </Card>
              )}
              {selectedStudent ? (
                <Card style={{ display: "grid", gap: 10 }}>
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 10 }}
                  >
                    <Avatar
                      name={
                        selectedStudent.display_name || selectedStudent.email
                      }
                      size={38}
                    />
                    <div style={{ display: "grid", gap: 2 }}>
                      <div style={{ fontSize: 17, fontWeight: 600 }}>
                        {selectedStudent.display_name}
                      </div>
                      <div style={{ fontSize: 12, color: D.muted }}>
                        {selectedStudent.email}
                      </div>
                      <div style={{ fontSize: 11, color: D.dim }}>
                        {selectedStudent.role_in_section} ·{" "}
                        {selectedStudent.membership_status}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(220px, 1fr))",
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
                      value={
                        selectedStudent.last_session_at ? "recent" : "none"
                      }
                      sub={formatLastSession(selectedStudent.last_session_at)}
                      color={
                        selectedStudent.last_session_at ? D.green : D.muted
                      }
                    />
                  </div>
                </Card>
              ) : null}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {loadingStudents && (
                  <div style={{ fontSize: 12, color: D.muted }}>
                    Loading roster...
                  </div>
                )}
                {!loadingStudents && students.length === 0 && (
                  <div style={{ fontSize: 12, color: D.dim }}>
                    No student memberships found for this section.
                  </div>
                )}
                {students.map((student) => (
                  <Card
                    key={student.user_id}
                    onClick={() => setSelectedStudentId(student.user_id)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      borderColor:
                        student.user_id === selectedStudentId
                          ? D.orangeBorder
                          : D.border,
                      background:
                        student.user_id === selectedStudentId
                          ? D.orangeGlow
                          : D.card,
                    }}
                  >
                    <Avatar name={student.display_name || student.email} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>
                        {student.display_name}
                      </div>
                      <div style={{ fontSize: 11, color: D.muted }}>
                        {student.email}
                      </div>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        flexWrap: "wrap",
                      }}
                    >
                      <Tag color={D.green}>
                        {student.session_count} sessions
                      </Tag>
                      <Tag color={D.blue}>{student.membership_status}</Tag>
                      <Btn
                        small
                        onClick={() => openStudentAnalytics(student.user_id)}
                      >
                        View analytics
                      </Btn>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          ) : tab === "analytics" ? (
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 18 }}>
                Section analytics <Tag color={D.green}>LIVE</Tag>
              </div>
              <Card style={{ marginBottom: 12, fontSize: 12, color: D.muted }}>
                Live Aurora-backed analytics for the selected section. This view
                stays scoped to the professor or TA memberships on that section.
                {activeAnalytics?.generated_at ? (
                  <span
                    style={{ display: "block", marginTop: 8, color: D.dim }}
                  >
                    Refreshed at {activeAnalytics.generated_at}
                  </span>
                ) : null}
              </Card>
              {analyticsError ? (
                <Card style={{ marginBottom: 12, color: D.red }}>
                  Analytics failed to load: {analyticsError}
                </Card>
              ) : null}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <Stat
                  label="// sessions_7d"
                  value={activeAnalytics?.sessions_last_7_days ?? 0}
                  sub="Aurora tutor_sessions"
                  color={D.orange}
                />
                <Stat
                  label="// active_students_7d"
                  value={activeAnalytics?.active_students_last_7_days ?? 0}
                  sub="distinct student authors"
                  color={D.blue}
                />
                <Stat
                  label="// section_roster"
                  value={selectedSection?.student_count ?? 0}
                  sub={
                    selectedSection
                      ? selectedSection.section_id
                      : "no section selected"
                  }
                  color={D.green}
                />
              </div>
              <Card style={{ marginBottom: 12 }}>
                <div
                  style={{
                    ...mono,
                    fontSize: 11,
                    color: D.muted,
                    marginBottom: 14,
                  }}
                >
                  // section_analytics
                </div>
                {loadingAnalytics ? (
                  <div style={{ fontSize: 12, color: D.muted }}>
                    Loading analytics...
                  </div>
                ) : activeAnalytics ? (
                  <ProfessorAnalyticsCharts
                    cognitive_progression={
                      activeAnalytics.cognitive_progression
                    }
                    pedagogical_actions={activeAnalytics.pedagogical_actions}
                    frustration_by_week={activeAnalytics.frustration_by_week}
                    time_utilization={activeAnalytics.time_utilization}
                  />
                ) : null}
              </Card>
              <Card style={{ marginBottom: 12 }}>
                <div
                  style={{
                    ...mono,
                    fontSize: 11,
                    color: D.muted,
                    marginBottom: 14,
                  }}
                >
                  // student_drill_down
                </div>
                {studentAnalyticsError ? (
                  <div style={{ color: D.red, fontSize: 12 }}>
                    Student analytics failed to load: {studentAnalyticsError}
                  </div>
                ) : loadingStudentAnalytics ? (
                  <div style={{ fontSize: 12, color: D.muted }}>
                    Loading student drill-down...
                  </div>
                ) : activeStudentAnalytics ? (
                  <div style={{ display: "grid", gap: 12 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        flexWrap: "wrap",
                      }}
                    >
                      <Avatar
                        name={
                          activeStudentAnalytics.student.display_name ||
                          activeStudentAnalytics.student.email
                        }
                        size={36}
                      />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 15, fontWeight: 600 }}>
                          {activeStudentAnalytics.student.display_name}
                        </div>
                        <div style={{ fontSize: 11, color: D.muted }}>
                          {activeStudentAnalytics.student.email}
                        </div>
                        <div style={{ fontSize: 11, color: D.dim }}>
                          {activeStudentAnalytics.student.membership_status} ·{" "}
                          {activeStudentAnalytics.student.role_in_section}
                        </div>
                      </div>
                      <div style={{ flex: 1 }} />
                      <Btn small onClick={() => setTab("students")}>
                        Back to roster
                      </Btn>
                    </div>

                    <div
                      style={{
                        display: "flex",
                        gap: 8,
                        borderBottom: `1px solid ${D.border}`,
                        paddingBottom: 12,
                      }}
                    >
                      <button
                        onClick={() => setStudentDrillDownTab("analytics")}
                        style={{
                          background:
                            studentDrillDownTab === "analytics"
                              ? D.surface
                              : "transparent",
                          border: `1px solid ${studentDrillDownTab === "analytics" ? D.border : "transparent"}`,
                          color: D.text,
                          padding: "6px 12px",
                          borderRadius: 6,
                          fontSize: 13,
                          cursor: "pointer",
                          fontWeight:
                            studentDrillDownTab === "analytics" ? 600 : 400,
                        }}
                      >
                        Analytics
                      </button>
                      <button
                        onClick={() => setStudentDrillDownTab("feedback")}
                        style={{
                          background:
                            studentDrillDownTab === "feedback"
                              ? D.surface
                              : "transparent",
                          border: `1px solid ${studentDrillDownTab === "feedback" ? D.border : "transparent"}`,
                          color: D.text,
                          padding: "6px 12px",
                          borderRadius: 6,
                          fontSize: 13,
                          cursor: "pointer",
                          fontWeight:
                            studentDrillDownTab === "feedback" ? 600 : 400,
                        }}
                      >
                        Feedback
                      </button>
                    </div>

                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        flexWrap: "wrap",
                        padding: 12,
                        background: D.surface,
                        borderRadius: 8,
                        border: `1px solid ${D.border}`,
                        marginTop: 4,
                      }}
                    >
                      <Stat
                        label="// sessions"
                        value={activeStudentAnalytics.total_sessions}
                        sub="total sessions"
                        color={D.orange}
                      />
                      <Stat
                        label="// requests"
                        value={activeStudentAnalytics.total_turns}
                        sub="total requests"
                        color={D.purple}
                      />
                      <Stat
                        label="// feedback"
                        value={`${activeStudentAnalytics.positive_feedback_count} / ${activeStudentAnalytics.negative_feedback_count}`}
                        sub="positive / negative"
                        color={D.blue}
                      />
                      <Stat
                        label="// last_activity"
                        value={
                          activeStudentAnalytics.last_activity_at
                            ? "recent"
                            : "none"
                        }
                        sub={formatLastSession(
                          activeStudentAnalytics.last_activity_at,
                        )}
                        color={
                          activeStudentAnalytics.last_activity_at
                            ? D.green
                            : D.muted
                        }
                      />
                      <Stat
                        label="// pastes"
                        value={activeStudentAnalytics.external_paste_count}
                        sub="external pastes detected"
                        color={
                          activeStudentAnalytics.external_paste_count > 0
                            ? D.red
                            : D.muted
                        }
                      />
                    </div>

                    {studentDrillDownTab === "analytics" && (
                      <>
                        <div
                          style={{
                            fontSize: 12,
                            color: D.dim,
                            lineHeight: 1.6,
                            marginTop: 12,
                          }}
                        >
                          The charts below show the student’s own activity
                          across the selected section.
                        </div>
                        <ProfessorAnalyticsCharts
                          cognitive_progression={
                            activeStudentAnalytics.cognitive_progression
                          }
                          pedagogical_actions={
                            activeStudentAnalytics.pedagogical_actions
                          }
                          frustration_by_week={
                            activeStudentAnalytics.frustration_by_week
                          }
                          time_utilization={
                            activeStudentAnalytics.time_utilization
                          }
                        />

                        {activeStudentAnalytics.paste_incidents &&
                          activeStudentAnalytics.paste_incidents.length > 0 && (
                            <div style={{ marginTop: 24 }}>
                              <div
                                style={{
                                  fontSize: 14,
                                  fontWeight: 600,
                                  marginBottom: 8,
                                  color: D.red,
                                }}
                              >
                                ⚠️ Paste Incidents
                              </div>
                              <div
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: 8,
                                }}
                              >
                                {activeStudentAnalytics.paste_incidents.map(
                                  (incident, i) => (
                                    <div
                                      key={i}
                                      style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        padding: 12,
                                        background: D.surface,
                                        border: `1px solid ${D.red}40`,
                                        borderRadius: 6,
                                        fontSize: 13,
                                      }}
                                    >
                                      <div>
                                        <span
                                          style={{
                                            fontWeight: 600,
                                            color: D.red,
                                          }}
                                        >
                                          Pasted {incident.pasted_char_count}{" "}
                                          characters
                                        </span>
                                        <div
                                          style={{
                                            ...mono,
                                            fontSize: 11,
                                            color: D.muted,
                                            marginTop: 4,
                                          }}
                                        >
                                          Session: {incident.session_id}
                                        </div>
                                      </div>
                                      <div style={{ color: D.muted }}>
                                        {incident.created_at
                                          ? new Date(
                                              incident.created_at,
                                            ).toLocaleString()
                                          : "Unknown"}
                                      </div>
                                    </div>
                                  ),
                                )}
                              </div>
                            </div>
                          )}
                      </>
                    )}

                    {studentDrillDownTab === "feedback" && (
                      <div style={{ marginTop: 12 }}>
                        {studentFeedbackError ? (
                          <div
                            style={{
                              color: D.red,
                              padding: 12,
                              background: `${D.red}10`,
                              borderRadius: 8,
                            }}
                          >
                            Failed to load feedback: {studentFeedbackError}
                          </div>
                        ) : studentFeedback ? (
                          <ProfessorStudentFeedback
                            feedback={studentFeedback.feedback}
                          />
                        ) : (
                          <div style={{ fontSize: 12, color: D.muted }}>
                            Loading feedback...
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: D.dim }}>
                    Pick a student from the roster to inspect individual
                    activity.
                  </div>
                )}
              </Card>
              <Card>
                <div
                  style={{
                    ...mono,
                    fontSize: 11,
                    color: D.muted,
                    marginBottom: 14,
                  }}
                >
                  // top_active_students
                </div>
                {loadingAnalytics ? (
                  <div style={{ fontSize: 12, color: D.muted }}>
                    Loading student highlights...
                  </div>
                ) : activeAnalytics?.top_students.length ? (
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 8 }}
                  >
                    {activeAnalytics.top_students.map((student) => (
                      <Card
                        key={student.user_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 12,
                          background: D.surface,
                          borderColor: D.border,
                        }}
                      >
                        <Avatar
                          name={student.display_name || student.email}
                          size={32}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, fontWeight: 500 }}>
                            {student.display_name}
                          </div>
                          <div style={{ fontSize: 11, color: D.muted }}>
                            {student.email}
                          </div>
                        </div>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            flexWrap: "wrap",
                          }}
                        >
                          <Tag color={D.orange}>
                            {student.session_count} sessions
                          </Tag>
                          <Tag color={D.blue}>{student.membership_status}</Tag>
                          <Btn
                            small
                            onClick={() =>
                              openStudentAnalytics(student.user_id)
                            }
                          >
                            View analytics
                          </Btn>
                        </div>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: D.dim }}>
                    No section activity has been recorded yet.
                  </div>
                )}
              </Card>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
