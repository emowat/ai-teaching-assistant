import { useEffect, useMemo, useRef, useState } from "react";

import { listAdminCourses, type AdminCourse } from "../../api/adminCoursesApi";
import { listAdminSections, type AdminSection } from "../../api/adminSectionsApi";
import {
  getAdminEvaluationConfig,
  getAdminEvaluationOverview,
  launchAdminEvaluationRun,
  listAdminEvaluationRuns,
  type EvaluationJudgeProvider,
  type EvaluationLaunchConfig,
  type EvaluationOverviewResponse,
  type EvaluationRunCreatePayload,
  type EvaluationRunArtifact,
  type EvaluationRunMetric,
  type EvaluationRunScope,
  type EvaluationRunStatus,
  type EvaluationRunSummary,
} from "../../api/adminEvaluationsApi";
import { Btn, Card, Stat, Tag } from "../../design/atoms";
import { D, mono } from "../../design/tokens";

interface OfflineEvalsPanelProps {
  accessToken: string;
}

type DatasetMode = "export" | "direct";

interface LaunchDraft {
  judge_provider: EvaluationJudgeProvider;
  judge_model: string;
  dataset_mode: DatasetMode;
  direct_dataset_s3_uri: string;
  course_id: string;
  section_id: string;
  start_date: string;
  end_date: string;
  run_label: string;
  notes: string;
}

const ACTIVE_RUN_STATUSES = new Set<EvaluationRunStatus>(["queued", "running"]);

function emptyLaunchDraft(defaults?: Partial<LaunchDraft>): LaunchDraft {
  return {
    judge_provider: defaults?.judge_provider ?? "openai",
    judge_model: defaults?.judge_model ?? "",
    dataset_mode: defaults?.dataset_mode ?? "export",
    direct_dataset_s3_uri: defaults?.direct_dataset_s3_uri ?? "",
    course_id: defaults?.course_id ?? "",
    section_id: defaults?.section_id ?? "",
    start_date: defaults?.start_date ?? "",
    end_date: defaults?.end_date ?? "",
    run_label: defaults?.run_label ?? "",
    notes: defaults?.notes ?? "",
  };
}

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatPct(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function statusColor(status: EvaluationRunStatus): string {
  switch (status) {
    case "succeeded":
      return D.green;
    case "failed":
    case "launch_failed":
      return D.red;
    case "queued":
    case "running":
      return D.yellow;
  }
}

function statusLabel(status: EvaluationRunStatus): string {
  return status.replaceAll("_", " ").toUpperCase();
}

function metricDisplayValue(metric: EvaluationRunMetric): string {
  if (typeof metric.metric_value === "number" && Number.isFinite(metric.metric_value)) {
    return metric.metric_value.toString();
  }
  if (metric.metric_text) {
    return metric.metric_text;
  }
  return "—";
}

function artifactHref(artifact: EvaluationRunArtifact): string {
  return (artifact as EvaluationRunArtifact & { download_url?: string | null }).download_url ?? artifact.s3_uri;
}

function runScopeLabel(run: EvaluationRunSummary): string {
  const parts: string[] = [];
  if (run.course_id) {
    parts.push(run.course_id);
  }
  if (run.section_id) {
    parts.push(run.section_id);
  }
  if (parts.length > 0) {
    return parts.join(" / ");
  }
  if (run.scope_start_date || run.scope_end_date) {
    const start = run.scope_start_date ?? "…";
    const end = run.scope_end_date ?? "…";
    return `${start} → ${end}`;
  }
  if (run.input_dataset_s3_uri) {
    return run.input_dataset_s3_uri;
  }
  return "Custom dataset";
}

function overviewCount(overview: EvaluationOverviewResponse | null, key: string): number {
  return Number(overview?.status_counts?.[key] ?? 0);
}

export function OfflineEvalsPanel({ accessToken }: OfflineEvalsPanelProps) {
  const [config, setConfig] = useState<EvaluationLaunchConfig | null>(null);
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [sections, setSections] = useState<AdminSection[]>([]);
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([]);
  const [overview, setOverview] = useState<EvaluationOverviewResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshingRuns, setRefreshingRuns] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const [launchDraft, setLaunchDraft] = useState<LaunchDraft>(emptyLaunchDraft());

  const selectedRun = runs.find((run) => run.evaluation_run_id === selectedRunId) ?? null;
  const selectedCourseSections = useMemo(
    () =>
      sections
        .filter((section) => section.course_id === launchDraft.course_id)
        .sort((left, right) => left.section_id.localeCompare(right.section_id)),
    [launchDraft.course_id, sections],
  );
  const activeRunCount = runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status)).length;

  const syncRuns = (nextRuns: EvaluationRunSummary[]) => {
    const sortedRuns = [...nextRuns].sort((left, right) => right.created_at.localeCompare(left.created_at));
    setRuns(sortedRuns);
    const currentSelectedId = selectedRunIdRef.current;
    const nextSelectedId =
      (currentSelectedId && sortedRuns.some((run) => run.evaluation_run_id === currentSelectedId)
        ? currentSelectedId
        : sortedRuns[0]?.evaluation_run_id ?? null);
    selectedRunIdRef.current = nextSelectedId;
    setSelectedRunId(nextSelectedId);
  };

  const refreshRuns = async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setRefreshingRuns(true);
    }
    setFormError(null);

    try {
      const [nextRuns, nextOverview] = await Promise.all([
        listAdminEvaluationRuns(accessToken, { limit: 25 }),
        getAdminEvaluationOverview(accessToken, 5),
      ]);
      syncRuns(nextRuns);
      setOverview(nextOverview);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to refresh evaluation runs.");
    } finally {
      if (!silent) {
        setRefreshingRuns(false);
      }
    }
  };

  useEffect(() => {
    let cancelled = false;

    const loadInitialState = async () => {
      try {
        const [nextConfig, nextCourses, nextSections, nextRuns, nextOverview] = await Promise.all([
          getAdminEvaluationConfig(accessToken),
          listAdminCourses(accessToken),
          listAdminSections(accessToken),
          listAdminEvaluationRuns(accessToken, { limit: 25 }),
          getAdminEvaluationOverview(accessToken, 5),
        ]);
        if (cancelled) {
          return;
        }

        setConfig(nextConfig);
        setCourses(nextCourses);
        setSections(nextSections);
        syncRuns(nextRuns);
        setOverview(nextOverview);
        setLaunchDraft((current) => {
          const nextCourseId =
            current.course_id || nextCourses[0]?.course_id || "";
          const nextSectionsForCourse = nextSectionsByCourse(nextSections, nextCourseId);
          const nextSectionId =
            current.section_id &&
            nextSectionsForCourse.some((section) => section.section_id === current.section_id)
              ? current.section_id
              : nextSectionsForCourse[0]?.section_id ?? "";
          return emptyLaunchDraft({
            judge_provider: nextConfig.default_judge_provider,
            judge_model: nextConfig.default_judge_model,
            course_id: nextCourseId,
            section_id: nextSectionId,
            dataset_mode: current.dataset_mode,
            direct_dataset_s3_uri: current.direct_dataset_s3_uri,
            start_date: current.start_date,
            end_date: current.end_date,
            run_label: current.run_label,
            notes: current.notes,
          });
        });
      } catch (err) {
        if (!cancelled) {
          setFormError(err instanceof Error ? err.message : "Unable to load evaluation settings.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadInitialState();

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  useEffect(() => {
    if (!selectedRunId) {
      return;
    }
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  useEffect(() => {
    if (launchDraft.dataset_mode !== "export") {
      return;
    }
    const nextSections = nextSectionsByCourse(sections, launchDraft.course_id);
    if (launchDraft.section_id && !nextSections.some((section) => section.section_id === launchDraft.section_id)) {
      setLaunchDraft((current) => ({
        ...current,
        section_id: nextSections[0]?.section_id ?? "",
      }));
    }
  }, [launchDraft.dataset_mode, launchDraft.course_id, launchDraft.section_id, sections]);

  const activeRunStatuses = runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status));

  useEffect(() => {
    if (activeRunStatuses.length === 0) {
      return;
    }

    let cancelled = false;
    const poll = () => {
      if (!cancelled) {
        void refreshRuns({ silent: true });
      }
    };

    const intervalId = window.setInterval(poll, 20_000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeRunStatuses.length, accessToken]);

  const handleLaunch = async () => {
    setLaunching(true);
    setFormError(null);
    setFormStatus(null);

    try {
      const nextModel = launchDraft.judge_model.trim();
      if (!nextModel) {
        throw new Error("Judge model is required.");
      }

      const payload: EvaluationRunCreatePayload =
        launchDraft.dataset_mode === "direct"
          ? {
              judge_provider: launchDraft.judge_provider,
              judge_model: nextModel,
              dataset_s3_uri: launchDraft.direct_dataset_s3_uri.trim() || null,
              run_label: launchDraft.run_label.trim() || undefined,
              notes: launchDraft.notes.trim() || undefined,
            }
          : {
              judge_provider: launchDraft.judge_provider,
              judge_model: nextModel,
              export_scope: {
                course_id: launchDraft.course_id.trim() || null,
                section_id: launchDraft.section_id.trim() || null,
                start_date: launchDraft.start_date || null,
                end_date: launchDraft.end_date || null,
              } satisfies EvaluationRunScope,
              run_label: launchDraft.run_label.trim() || undefined,
              notes: launchDraft.notes.trim() || undefined,
            };

      if (launchDraft.dataset_mode === "direct") {
        if (!payload.dataset_s3_uri) {
          throw new Error("Dataset S3 URI is required for direct launch mode.");
        }
      } else if (!payload.export_scope?.course_id) {
        throw new Error("Select a course for the export-based launch path.");
      }

      const launched = await launchAdminEvaluationRun(accessToken, payload);
      setFormStatus(`Launched ${launched.evaluation_run_id}.`);
      selectedRunIdRef.current = launched.evaluation_run_id;
      setSelectedRunId(launched.evaluation_run_id);
      setRuns((current) => {
        const next = current.filter((run) => run.evaluation_run_id !== launched.evaluation_run_id);
        next.unshift(launched);
        next.sort((left, right) => right.created_at.localeCompare(left.created_at));
        return next;
      });
      void refreshRuns({ silent: true });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to launch evaluation run.");
    } finally {
      setLaunching(false);
    }
  };

  const providerOptions = config?.supported_judge_providers ?? ["openai", "bedrock"];
  const defaultModelPlaceholder = config?.default_judge_model ?? "anthropic.claude-haiku-4-5";

  const summaryCards = [
    { label: "Total Runs", value: overview?.total_runs?.toString() ?? "..." },
    { label: "Active Runs", value: overview?.active_runs?.toString() ?? "..." },
    { label: "Queued", value: overviewCount(overview, "queued").toString() },
    { label: "Running", value: overviewCount(overview, "running").toString() },
    { label: "Succeeded", value: overviewCount(overview, "succeeded").toString() },
    { label: "Failed", value: overviewCount(overview, "failed").toString() },
  ];

  if (loading) {
    return (
      <Card style={{ display: "grid", gap: 8, maxWidth: 820 }}>
        <div style={{ ...mono, fontSize: 11, color: D.muted }}>// offline_evals</div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>Loading Offline Evals...</div>
        <div style={{ fontSize: 13, color: D.muted }}>
          Loading judge providers, recent runs, and the course/section scope picker.
        </div>
      </Card>
    );
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card style={{ display: "grid", gap: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Offline Evals</div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
              Launch offline evaluation runs from canonical turn snapshot exports and review their artifacts.
            </div>
            <div style={{ fontSize: 11, color: D.dim, marginTop: 6, lineHeight: 1.45 }}>
              Normal launches use a course or section scope and export matching snapshots automatically.
              Direct S3 dataset URIs remain available for advanced testing.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Tag color={D.blue}>{overview?.total_runs ?? runs.length} total</Tag>
            <Tag color={D.yellow}>{activeRunCount} active</Tag>
            <Tag color={D.green}>{overviewCount(overview, "succeeded")} passed</Tag>
            <Btn small variant="ghost" onClick={() => void refreshRuns()} disabled={refreshingRuns || launching}>
              {refreshingRuns ? "Refreshing..." : "Refresh"}
            </Btn>
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 12,
          }}
        >
          {summaryCards.map((card) => (
            <Stat key={card.label} label={card.label} value={card.value} />
          ))}
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Judge provider</span>
              <select
                value={launchDraft.judge_provider}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    judge_provider: event.target.value as EvaluationJudgeProvider,
                  }))
                }
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              >
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Judge model</span>
              <input
                value={launchDraft.judge_model}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    judge_model: event.target.value,
                  }))
                }
                placeholder={defaultModelPlaceholder}
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
              <span style={{ fontSize: 12, color: D.muted }}>Dataset mode</span>
              <select
                value={launchDraft.dataset_mode}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    dataset_mode: event.target.value as DatasetMode,
                  }))
                }
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              >
                <option value="export">Export course / section scope</option>
                <option value="direct">Direct S3 URI</option>
              </select>
            </label>
          </div>

          {launchDraft.dataset_mode === "direct" ? (
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Dataset S3 URI</span>
              <input
                value={launchDraft.direct_dataset_s3_uri}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    direct_dataset_s3_uri: event.target.value,
                  }))
                }
                placeholder="s3://bucket/path/to/turn_snapshots.jsonl"
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
            </label>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Course</span>
                  <select
                    value={launchDraft.course_id}
                    onChange={(event) =>
                      setLaunchDraft((current) => ({
                        ...current,
                        course_id: event.target.value,
                        section_id: "",
                      }))
                    }
                    style={{
                      background: D.bg,
                      color: D.text,
                      border: `1px solid ${D.border}`,
                      borderRadius: 8,
                      padding: "10px 12px",
                    }}
                  >
                    <option value="">Select a course</option>
                    {courses.map((course) => (
                      <option key={course.course_id} value={course.course_id}>
                        {course.course_id.toUpperCase()} — {course.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Section</span>
                  <select
                    value={launchDraft.section_id}
                    onChange={(event) =>
                      setLaunchDraft((current) => ({
                        ...current,
                        section_id: event.target.value,
                      }))
                    }
                    disabled={!launchDraft.course_id}
                    style={{
                      background: D.bg,
                      color: D.text,
                      border: `1px solid ${D.border}`,
                      borderRadius: 8,
                      padding: "10px 12px",
                    }}
                  >
                    <option value="">All sections</option>
                    {selectedCourseSections.map((section) => (
                      <option key={section.section_id} value={section.section_id}>
                        {section.section_id} — {section.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Start date</span>
                  <input
                    type="date"
                    value={launchDraft.start_date}
                    onChange={(event) =>
                      setLaunchDraft((current) => ({
                        ...current,
                        start_date: event.target.value,
                      }))
                    }
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
                  <span style={{ fontSize: 12, color: D.muted }}>End date</span>
                  <input
                    type="date"
                    value={launchDraft.end_date}
                    onChange={(event) =>
                      setLaunchDraft((current) => ({
                        ...current,
                        end_date: event.target.value,
                      }))
                    }
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
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Run label</span>
              <input
                value={launchDraft.run_label}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    run_label: event.target.value,
                  }))
                }
                placeholder="Weekly professor QA"
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
              <span style={{ fontSize: 12, color: D.muted }}>Notes</span>
              <input
                value={launchDraft.notes}
                onChange={(event) =>
                  setLaunchDraft((current) => ({
                    ...current,
                    notes: event.target.value,
                  }))
                }
                placeholder="Optional launch notes"
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
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <Btn variant="primary" small onClick={handleLaunch} disabled={launching}>
            {launching ? "Launching..." : "Launch evaluation"}
          </Btn>
          <div style={{ fontSize: 12, color: D.muted }}>
            The worker reads canonical turn snapshots from S3, runs the judge provider, and stores artifacts back to S3.
          </div>
        </div>

        {formError && <div style={{ color: D.red, fontSize: 12 }}>{formError}</div>}
        {formStatus && <div style={{ color: D.green, fontSize: 12 }}>{formStatus}</div>}
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 380px) minmax(0, 1fr)", gap: 14 }}>
        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>Recent runs</div>
              <div style={{ fontSize: 12, color: D.muted, marginTop: 3 }}>Click a run to inspect its summary and artifacts.</div>
            </div>
            <Tag color={D.blue}>{runs.length} listed</Tag>
          </div>

          {runs.length === 0 ? (
            <div style={{ color: D.muted, fontSize: 13, padding: "12px 0" }}>
              No evaluation runs have been launched yet.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              {runs.map((run) => {
                const selected = run.evaluation_run_id === selectedRunId;
                return (
                  <button
                    key={run.evaluation_run_id}
                    type="button"
                    onClick={() => {
                      selectedRunIdRef.current = run.evaluation_run_id;
                      setSelectedRunId(run.evaluation_run_id);
                    }}
                    style={{
                      textAlign: "left",
                      borderRadius: 14,
                      border: `1px solid ${selected ? D.orangeBorder : D.border}`,
                      background: selected ? "#fff" : D.card,
                      padding: 12,
                      cursor: "pointer",
                      boxShadow: selected ? "0 8px 18px rgba(249, 115, 22, 0.08)" : "none",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{run.run_label || run.evaluation_run_id}</div>
                      <Tag color={statusColor(run.status)}>{statusLabel(run.status)}</Tag>
                    </div>
                    <div style={{ fontSize: 11, color: D.muted, marginTop: 6 }}>{run.judge_provider} / {run.judge_model}</div>
                    <div style={{ fontSize: 11, color: D.dim, marginTop: 4 }}>{runScopeLabel(run)}</div>
                    <div style={{ fontSize: 11, color: D.dim, marginTop: 4 }}>{formatTimestamp(run.created_at)}</div>
                  </button>
                );
              })}
            </div>
          )}
        </Card>

        <Card style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>
                {selectedRun ? selectedRun.run_label || selectedRun.evaluation_run_id : "Run details"}
              </div>
              <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
                {selectedRun ? selectedRun.notes || "No notes provided." : "Select a run to inspect its results."}
              </div>
            </div>
            {selectedRun && (
              <Tag color={statusColor(selectedRun.status)}>{statusLabel(selectedRun.status)}</Tag>
            )}
          </div>

          {selectedRun === null ? (
            <div style={{ color: D.muted, fontSize: 13 }}>
              Choose a run from the left to review its metrics, artifacts, and result prefix.
            </div>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                <Stat label="Total rows" value={selectedRun.total_rows.toString()} />
                <Stat label="Usable rows" value={selectedRun.usable_rows.toString()} color={D.green} />
                <Stat label="Skipped" value={selectedRun.skipped_rows.toString()} color={D.red} />
                <Stat label="Macro pass" value={formatPct(selectedRun.macro_pass_rate)} color={D.blue} />
                <Stat label="Micro pass" value={formatPct(selectedRun.micro_pass_rate)} color={D.blue} />
                <Stat label="Drift" value={formatPct(selectedRun.drift_rate)} color={D.orange} />
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 10,
                }}
              >
                <Card style={{ padding: 12 }}>
                  <div style={{ fontSize: 11, color: D.muted, ...mono }}>// judge_route</div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    {selectedRun.judge_provider} / {selectedRun.judge_model}
                  </div>
                </Card>
                <Card style={{ padding: 12 }}>
                  <div style={{ fontSize: 11, color: D.muted, ...mono }}>// dataset</div>
                  <div style={{ fontSize: 12, color: D.text, marginTop: 6, wordBreak: "break-word" }}>
                    {selectedRun.input_dataset_s3_uri}
                  </div>
                </Card>
                <Card style={{ padding: 12 }}>
                  <div style={{ fontSize: 11, color: D.muted, ...mono }}>// results_prefix</div>
                  <div style={{ fontSize: 12, color: D.text, marginTop: 6, wordBreak: "break-word" }}>
                    {selectedRun.results_s3_prefix}
                  </div>
                </Card>
                <Card style={{ padding: 12 }}>
                  <div style={{ fontSize: 11, color: D.muted, ...mono }}>// requested_by</div>
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    {selectedRun.requested_by_email || selectedRun.requested_by_cognito_sub}
                  </div>
                </Card>
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ fontSize: 12, color: D.muted, ...mono }}>// summary</div>
                <div
                  style={{
                    padding: 12,
                    borderRadius: 12,
                    background: D.surface,
                    border: `1px solid ${D.border}`,
                    fontSize: 13,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {JSON.stringify(selectedRun.summary, null, 2)}
                </div>
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ fontSize: 12, color: D.muted, ...mono }}>// metrics</div>
                {selectedRun.metrics.length === 0 ? (
                  <div style={{ color: D.muted, fontSize: 13 }}>No granular metrics were recorded yet.</div>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${D.border}`, color: D.muted }}>
                        <th style={{ textAlign: "left", padding: "8px 6px" }}>Group</th>
                        <th style={{ textAlign: "left", padding: "8px 6px" }}>Metric</th>
                        <th style={{ textAlign: "left", padding: "8px 6px" }}>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRun.metrics.map((metric) => (
                        <tr key={metric.metric_id} style={{ borderBottom: `1px solid ${D.border}` }}>
                          <td style={{ padding: "8px 6px", ...mono, fontSize: 11 }}>{metric.metric_group}</td>
                          <td style={{ padding: "8px 6px" }}>{metric.metric_name}</td>
                          <td style={{ padding: "8px 6px", color: D.dim, whiteSpace: "pre-wrap" }}>
                            {metricDisplayValue(metric)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ fontSize: 12, color: D.muted, ...mono }}>// artifacts</div>
                {selectedRun.artifacts.length === 0 ? (
                  <div style={{ color: D.muted, fontSize: 13 }}>No artifacts uploaded yet.</div>
                ) : (
                  <div style={{ display: "grid", gap: 8 }}>
                    {selectedRun.artifacts.map((artifact) => (
                      <Card key={artifact.artifact_id} style={{ padding: 12 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 600 }}>{artifact.label}</div>
                            <div style={{ fontSize: 11, color: D.muted, marginTop: 4 }}>
                              {artifact.artifact_type} · {artifact.content_type || "unknown content type"}
                            </div>
                          </div>
                          <Tag color={D.blue}>{artifact.artifact_type}</Tag>
                        </div>
                        <div style={{ marginTop: 8, fontSize: 12, color: D.dim, wordBreak: "break-word" }}>
                          <a href={artifactHref(artifact)} target="_blank" rel="noreferrer">
                            {artifactHref(artifact)}
                          </a>
                        </div>
                      </Card>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

function nextSectionsByCourse(sections: AdminSection[], courseId: string): AdminSection[] {
  return sections.filter((section) => section.course_id === courseId);
}
