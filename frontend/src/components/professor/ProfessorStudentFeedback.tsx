import { Card, Tag } from "../../design/atoms";
import { D, mono } from "../../design/tokens";
import type { ProfessorStudentFeedbackEntry } from "../../api/professorSectionsApi";

export function ProfessorStudentFeedback({
  feedback,
}: {
  feedback: ProfessorStudentFeedbackEntry[];
}) {
  if (feedback.length === 0) {
    return (
      <div style={{ color: D.muted, padding: 24, textAlign: "center" }}>
        No Feedback Received
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {feedback.map((f, i) => (
        <Card
          key={i}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            padding: 16,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 16 }}>
                {f.rating === "positive" ? "👍" : "👎"}
              </span>
              <span
                style={{
                  fontWeight: 600,
                  color: f.rating === "positive" ? D.green : D.red,
                }}
              >
                {f.rating === "positive" ? "Positive" : "Negative"}
              </span>
              {f.explanation && (
                <span style={{ fontSize: 14, color: D.text, marginLeft: 8 }}>
                  "{f.explanation}"
                </span>
              )}
            </div>
            <div style={{ ...mono, fontSize: 11, color: D.muted }}>
              {f.created_at
                ? new Date(f.created_at).toLocaleString()
                : "Unknown date"}{" "}
              • Turn {f.turn_index}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              marginTop: 8,
            }}
          >
            {f.rag_sources && f.rag_sources.length > 0 && (
              <>
                <div style={{ fontSize: 12, color: D.muted, ...mono }}>
                  // rag_sources
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {f.rag_sources.map((src) => (
                    <Tag key={src} color={D.orange}>
                      {src}
                    </Tag>
                  ))}
                </div>
              </>
            )}

            <div
              style={{ fontSize: 12, color: D.muted, ...mono, marginTop: 4 }}
            >
              // student_message
            </div>
            <div
              style={{
                background: `${D.blue}08`,
                padding: 12,
                borderRadius: 6,
                fontSize: 13,
                borderLeft: `3px solid ${D.blue}`,
              }}
            >
              {f.student_message || (
                <span style={{ color: D.muted, fontStyle: "italic" }}>
                  No message text
                </span>
              )}
            </div>

            {f.cot && Object.keys(f.cot).length > 0 && (
              <>
                <div
                  style={{
                    fontSize: 12,
                    color: D.muted,
                    ...mono,
                    marginTop: 4,
                  }}
                >
                  // chain_of_thought
                </div>
                <div
                  style={{
                    background: D.surface,
                    padding: 12,
                    borderRadius: 6,
                    fontSize: 12,
                    border: `1px solid ${D.border}`,
                  }}
                >
                  {Object.entries(f.cot).map(([key, val]) => (
                    <div key={key} style={{ marginBottom: 4 }}>
                      <span style={{ fontWeight: 600, color: D.muted }}>
                        {key}:{" "}
                      </span>
                      <span style={{ color: D.text }}>
                        {key === "Pedagogical_Action" && typeof val === "string"
                          ? val.match(/([A-Z_]{2,})/)
                            ? val
                                .match(/([A-Z_]{2,})/)![1]
                                .split("_")
                                .map(
                                  (w) =>
                                    w.charAt(0).toUpperCase() +
                                    w.slice(1).toLowerCase(),
                                )
                                .join(" ")
                            : "None"
                          : String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            <div
              style={{ fontSize: 12, color: D.muted, ...mono, marginTop: 4 }}
            >
              // ai_response
            </div>
            <div
              style={{
                background: `${D.purple}08`,
                padding: 12,
                borderRadius: 6,
                fontSize: 13,
                borderLeft: `3px solid ${D.purple}`,
                whiteSpace: "pre-wrap",
              }}
            >
              {f.ai_message ? (
                f.ai_message
                  .replace(/<think>[\s\S]*?<\/think>/g, "")
                  .replace(/<analysis>[\s\S]*?<\/analysis>/g, "")
                  .trim()
              ) : (
                <span style={{ color: D.muted, fontStyle: "italic" }}>
                  No response text
                </span>
              )}
            </div>
          </div>
          <div
            style={{
              fontSize: 11,
              color: D.dim,
              ...mono,
              textAlign: "right",
              marginTop: 8,
            }}
          >
            Session ID: {f.session_id}
          </div>
        </Card>
      ))}
    </div>
  );
}
