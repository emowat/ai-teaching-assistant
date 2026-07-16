import { useCallback, useEffect, useRef, useState } from "react";

import {
  getTaEffectivenessRoster,
  getTaEffectivenessSessionTurns,
  getTaEffectivenessStudentDetail,
  launchTaEffectivenessRefresh,
  type TaEffectivenessMetricResult,
  type TaEffectivenessRosterEntry,
  type TaEffectivenessSectionRoster,
  type TaEffectivenessSessionScore,
  type TaEffectivenessSessionTurns,
  type TaEffectivenessStudentDetail,
} from "../../api/professorTaEffectivenessApi";
import { Btn, Card, Tag } from "../../design/atoms";
import { D, mono } from "../../design/tokens";

interface TaEffectivenessPanelProps {
  mode: "roster" | "drilldown";
  sectionId: string;
  accessToken: string;
  studentUserId?: string | null;
  onSelectStudent?: (studentUserId: string) => void;
}

const POLL_INTERVAL_MS = 20_000;
const MAX_POLL_ATTEMPTS = 30; // ~10 minutes

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

// client.ts wraps API errors as `Error("API error <status>: <raw body>")`,
// and FastAPI error bodies are `{"detail": "..."}` JSON. Unwrap both layers
// so the UI shows the backend's actual message (e.g. "No activity to
// evaluate for section cs50-01 (2026-06-01 to 2026-07-16).") instead of the
// raw "API error 400: {...}" text.
function friendlyErrorMessage(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) {
    return fallback;
  }
  const match = err.message.match(/^API error \d+: ([\s\S]*)$/);
  const raw = match ? match[1] : err.message;
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    // raw wasn't JSON — fall through to the raw text below.
  }
  return raw.trim() || fallback;
}

function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatMetricLabel(name: string): string {
  return name
    .split("_")
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

function scoreColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return D.dim;
  }
  if (value >= 0.8) return D.green;
  if (value >= 0.5) return D.yellow;
  return D.red;
}

function metricValueColor(value: TaEffectivenessMetricResult["value"]): string {
  if (value === "NA" || value === "N/A" || value === null || value === undefined) {
    return D.dim;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isNaN(parsed)) {
    return parsed >= 1 ? D.green : D.red;
  }
  const normalized = String(value).trim().toUpperCase();
  if (normalized === "PASS") return D.green;
  if (normalized === "FAIL") return D.red;
  return D.dim;
}

function metricValueLabel(value: TaEffectivenessMetricResult["value"]): string {
  if (value === "NA" || value === "N/A" || value === null || value === undefined) {
    return "N/A";
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isNaN(parsed)) {
    return parsed >= 1 ? "Pass" : "Fail";
  }
  return String(value);
}

function MetricResultList({
  results,
}: {
  results: Record<string, TaEffectivenessMetricResult>;
}) {
  const entries = Object.entries(results);
  if (entries.length === 0) {
    return <div style={{ fontSize: 12, color: D.muted }}>No metric results recorded.</div>;
  }
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {entries.map(([name, result]) => (
        <div key={name} style={{ display: "grid", gap: 2 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{formatMetricLabel(name)}</div>
            <Tag color={metricValueColor(result.value)}>{metricValueLabel(result.value)}</Tag>
          </div>
          {result.reason && (
            <div style={{ fontSize: 11, color: D.muted }}>{result.reason}</div>
          )}
        </div>
      ))}
    </div>
  );
}

function SessionTurnsPanel({
  sectionId,
  session,
  accessToken,
}: {
  sectionId: string;
  session: TaEffectivenessSessionScore;
  accessToken: string;
}) {
  const [turns, setTurns] = useState<TaEffectivenessSessionTurns | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTaEffectivenessSessionTurns(
      sectionId,
      session.session_id,
      session.evaluation_run_id,
      accessToken,
    )
      .then((result) => {
        if (!cancelled) setTurns(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(friendlyErrorMessage(err, "Unable to load turn scores."));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sectionId, session.session_id, session.evaluation_run_id, accessToken]);

  if (loading) {
    return <div style={{ fontSize: 12, color: D.muted, padding: "8px 0" }}>Loading turns…</div>;
  }
  if (error) {
    return <div style={{ fontSize: 12, color: D.red, padding: "8px 0" }}>{error}</div>;
  }
  if (!turns || turns.turns.length === 0) {
    return <div style={{ fontSize: 12, color: D.muted, padding: "8px 0" }}>No per-turn scores recorded for this session.</div>;
  }

  return (
    <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
      {turns.turns.map((turn) => (
        <Card key={turn.turn_id} style={{ padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
            <div style={{ fontSize: 12, fontWeight: 700, ...mono }}>
              Turn {turn.turn_index ?? "?"}
            </div>
            <Tag color={scoreColor(turn.pedagogical_turn_score)}>
              {formatScore(turn.pedagogical_turn_score)}
            </Tag>
          </div>
          <div style={{ marginTop: 8 }}>
            <MetricResultList results={turn.micro_metric_results} />
          </div>
        </Card>
      ))}
    </div>
  );
}

function SessionList({
  sectionId,
  sessions,
  accessToken,
}: {
  sectionId: string;
  sessions: TaEffectivenessSessionScore[];
  accessToken: string;
}) {
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);

  if (sessions.length === 0) {
    return (
      <div style={{ color: D.muted, fontSize: 13, padding: "12px 0" }}>
        No scored sessions yet for this student. Run an evaluation for this section to populate scores.
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      {sessions.map((session) => {
        const expanded = expandedSessionId === session.session_id;
        return (
          <Card key={`${session.evaluation_run_id}-${session.session_id}`} style={{ padding: 14 }}>
            <button
              type="button"
              onClick={() => setExpandedSessionId(expanded ? null : session.session_id)}
              style={{
                all: "unset",
                cursor: "pointer",
                display: "block",
                width: "100%",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{formatTimestamp(session.scored_at)}</div>
                  <div style={{ fontSize: 11, color: D.muted, marginTop: 2 }}>
                    {session.mode || "session"} · {session.turn_count} turn{session.turn_count === 1 ? "" : "s"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {session.drift_flag && <Tag color={D.red}>Drift</Tag>}
                  {session.code_leak_turn_index !== null && <Tag color={D.red}>Code leak</Tag>}
                  <Tag color={scoreColor(session.pedagogical_impact_score)}>
                    Impact {formatScore(session.pedagogical_impact_score)}
                  </Tag>
                  <Tag color={scoreColor(session.session_effectiveness_score)}>
                    Effectiveness {formatScore(session.session_effectiveness_score)}
                  </Tag>
                </div>
              </div>
            </button>
            {expanded && (
              <div style={{ marginTop: 12, display: "grid", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 11, color: D.muted, ...mono, marginBottom: 6 }}>
                    // session_metrics
                  </div>
                  <MetricResultList results={session.macro_metric_results} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: D.muted, ...mono, marginBottom: 6 }}>
                    // per_turn_scores
                  </div>
                  <SessionTurnsPanel sectionId={sectionId} session={session} accessToken={accessToken} />
                </div>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function rosterMaxScoredAt(roster: TaEffectivenessSectionRoster | null): string {
  if (!roster) return "";
  let max = "";
  for (const entry of roster.entries) {
    if (entry.last_scored_at > max) {
      max = entry.last_scored_at;
    }
  }
  return max;
}

function RosterRow({
  entry,
  onSelect,
}: {
  entry: TaEffectivenessRosterEntry;
  onSelect?: (studentUserId: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect?.(entry.student.user_id)}
      style={{
        all: "unset",
        cursor: onSelect ? "pointer" : "default",
        display: "block",
        width: "100%",
      }}
    >
      <Card style={{ padding: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>
              {entry.student.display_name || entry.student.email}
            </div>
            <div style={{ fontSize: 11, color: D.muted, marginTop: 2 }}>
              {entry.session_count} scored session{entry.session_count === 1 ? "" : "s"} · last scored {formatTimestamp(entry.last_scored_at)}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {entry.has_code_leak && <Tag color={D.red}>Code leak</Tag>}
            {entry.drift_rate !== null && entry.drift_rate > 0 && (
              <Tag color={D.red}>Drift {formatScore(entry.drift_rate)}</Tag>
            )}
            <Tag color={scoreColor(entry.avg_pedagogical_impact)}>
              Impact {formatScore(entry.avg_pedagogical_impact)}
            </Tag>
            <Tag color={scoreColor(entry.avg_session_effectiveness)}>
              Effectiveness {formatScore(entry.avg_session_effectiveness)}
            </Tag>
          </div>
        </div>
      </Card>
    </button>
  );
}

export function TaEffectivenessPanel({
  mode,
  sectionId,
  accessToken,
  studentUserId,
  onSelectStudent,
}: TaEffectivenessPanelProps) {
  const [roster, setRoster] = useState<TaEffectivenessSectionRoster | null>(null);
  const [studentDetail, setStudentDetail] = useState<TaEffectivenessStudentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [launchMessage, setLaunchMessage] = useState<string | null>(null);
  const [refreshStartDate, setRefreshStartDate] = useState(todayIso());
  const [refreshEndDate, setRefreshEndDate] = useState(todayIso());
  const pollBaselineRef = useRef<string>("");
  const pollAttemptsRef = useRef(0);

  const loadRoster = useCallback(
    async (options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (!silent) setLoading(true);
      try {
        const result = await getTaEffectivenessRoster(sectionId, accessToken);
        setRoster(result);
        setError(null);
        return result;
      } catch (err) {
        setError(friendlyErrorMessage(err, "Unable to load TA effectiveness roster."));
        return null;
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [sectionId, accessToken],
  );

  const loadStudentDetail = useCallback(async () => {
    if (!studentUserId) return;
    setLoading(true);
    try {
      const result = await getTaEffectivenessStudentDetail(sectionId, studentUserId, accessToken);
      setStudentDetail(result);
      setError(null);
    } catch (err) {
      setError(friendlyErrorMessage(err, "Unable to load student TA effectiveness detail."));
    } finally {
      setLoading(false);
    }
  }, [sectionId, studentUserId, accessToken]);

  useEffect(() => {
    if (mode === "roster") {
      void loadRoster();
    }
  }, [mode, loadRoster]);

  useEffect(() => {
    if (mode === "drilldown") {
      void loadStudentDetail();
    }
  }, [mode, loadStudentDetail]);

  // Poll the roster read-endpoint after launching a refresh (professors have
  // no access to an admin run-status endpoint), stopping once a session gets
  // a newer scored_at than anything seen before the launch, or after a
  // bounded number of attempts.
  useEffect(() => {
    if (!launching || mode !== "roster") {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      pollAttemptsRef.current += 1;
      const next = await loadRoster({ silent: true });
      if (cancelled) return;
      const nextMax = rosterMaxScoredAt(next);
      if (nextMax && nextMax > pollBaselineRef.current) {
        setLaunching(false);
        setLaunchMessage("New evaluation results are in.");
        return;
      }
      if (pollAttemptsRef.current >= MAX_POLL_ATTEMPTS) {
        setLaunching(false);
        setLaunchMessage("Evaluation is taking longer than expected — check back soon.");
      }
    };
    const intervalId = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [launching, mode, loadRoster]);

  const handleLaunchRefresh = async () => {
    if (refreshStartDate > refreshEndDate) {
      setLaunchMessage("Start date must be on or before end date.");
      return;
    }
    setLaunching(true);
    setLaunchMessage(null);
    pollBaselineRef.current = rosterMaxScoredAt(roster);
    pollAttemptsRef.current = 0;
    try {
      await launchTaEffectivenessRefresh(sectionId, accessToken, {
        start_date: refreshStartDate,
        end_date: refreshEndDate,
      });
      setLaunchMessage("Evaluation launched — this can take several minutes.");
    } catch (err) {
      setLaunching(false);
      setLaunchMessage(friendlyErrorMessage(err, "Unable to launch a new evaluation."));
    }
  };

  if (mode === "roster") {
    return (
      <Card style={{ display: "grid", gap: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>TA Effectiveness</div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 3 }}>
              LLM-judge scores per student, worst effectiveness first. Click a student to drill in.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {roster && (
              <Tag color={D.blue}>Updated {formatTimestamp(rosterMaxScoredAt(roster) || roster.generated_at)}</Tag>
            )}
            <label style={{ fontSize: 11, color: D.muted, display: "flex", alignItems: "center", gap: 4 }}>
              From
              <input
                type="date"
                value={refreshStartDate}
                max={refreshEndDate}
                onChange={(event) => setRefreshStartDate(event.target.value)}
                disabled={launching}
                style={{
                  border: `1px solid ${D.border}`,
                  borderRadius: 6,
                  padding: "4px 6px",
                  fontSize: 12,
                  color: D.text,
                  background: D.card,
                }}
              />
            </label>
            <label style={{ fontSize: 11, color: D.muted, display: "flex", alignItems: "center", gap: 4 }}>
              To
              <input
                type="date"
                value={refreshEndDate}
                min={refreshStartDate}
                max={todayIso()}
                onChange={(event) => setRefreshEndDate(event.target.value)}
                disabled={launching}
                style={{
                  border: `1px solid ${D.border}`,
                  borderRadius: 6,
                  padding: "4px 6px",
                  fontSize: 12,
                  color: D.text,
                  background: D.card,
                }}
              />
            </label>
            <Btn variant="ghost" small onClick={handleLaunchRefresh} disabled={launching}>
              {launching ? "Evaluating…" : "Run new evaluation"}
            </Btn>
          </div>
        </div>

        {launchMessage && (
          <div style={{ fontSize: 12, color: launching ? D.muted : D.green }}>{launchMessage}</div>
        )}
        {error && <div style={{ fontSize: 12, color: D.red }}>{error}</div>}

        {loading ? (
          <div style={{ fontSize: 13, color: D.muted, padding: "12px 0" }}>Loading…</div>
        ) : !roster || roster.entries.length === 0 ? (
          <div style={{ fontSize: 13, color: D.muted, padding: "12px 0" }}>
            No TA effectiveness scores yet for this section. Run an evaluation to populate this roster.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {roster.entries.map((entry) => (
              <RosterRow key={entry.student.user_id} entry={entry} onSelect={onSelectStudent} />
            ))}
          </div>
        )}
      </Card>
    );
  }

  // drilldown mode
  return (
    <Card style={{ display: "grid", gap: 14 }}>
      <div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>
          {studentDetail ? studentDetail.student.display_name || studentDetail.student.email : "TA Effectiveness"}
        </div>
        <div style={{ fontSize: 12, color: D.muted, marginTop: 3 }}>
          Scored sessions, most recent first. Click a session to see per-turn judge scores.
        </div>
      </div>

      {error && <div style={{ fontSize: 12, color: D.red }}>{error}</div>}

      {loading ? (
        <div style={{ fontSize: 13, color: D.muted, padding: "12px 0" }}>Loading…</div>
      ) : (
        <SessionList
          sectionId={sectionId}
          sessions={studentDetail?.sessions ?? []}
          accessToken={accessToken}
        />
      )}
    </Card>
  );
}
