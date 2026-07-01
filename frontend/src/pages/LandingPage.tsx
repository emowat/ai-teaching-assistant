import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { getRedirectOrigin, getRedirectUri, hasOriginMismatch } from "../auth/cognitoConfig";
import { Btn, Card, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import rabbitMascot from "../assets/mascot.png";
import type { AppView } from "../types/navigation";

interface LandingPageProps {
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

const featureCards = [
  {
    icon: "🤔",
    tag: "Socratic first",
    color: D.orange,
    title: "The rabbit asks the next best question",
    desc:
      "CodingRabbit nudges students toward the answer instead of dropping a solution on top of the problem.",
  },
  {
    icon: "📚",
    tag: "Course aware",
    color: D.blue,
    title: "Only approved course material is in scope",
    desc:
      "RAG stays tied to the professor-approved corpus, so the tutor stays aligned with the current course.",
  },
  {
    icon: "🔒",
    tag: "Guardrailed",
    color: D.green,
    title: "Hints stay useful and safe",
    desc:
      "Input and output guardrails keep the conversation focused, constructive, and appropriate for the assignment.",
  },
] as const;

const quickFacts = [
  "Cognito login",
  "Aurora-backed routing",
  "Guardrails on by default",
  "CloudFront delivery",
] as const;

export function LandingPage({ onNavigate, demoMode = false }: LandingPageProps) {
  const auth = useAuth();
  const [hover, setHover] = useState<string | null>(null);

  const handleLogin = () => {
    void auth.signinRedirect();
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background:
          "radial-gradient(circle at top left, rgba(249,115,22,0.16), transparent 26%), radial-gradient(circle at top right, rgba(37,99,235,0.10), transparent 24%), linear-gradient(180deg, #fffdf8 0%, #f8f2e8 100%)",
        color: D.text,
        fontFamily: "var(--font-sans)",
        overflowY: "auto",
      }}
    >
      <nav
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 48px",
          height: 68,
          borderBottom: `1px solid ${D.border}`,
          position: "sticky",
          top: 0,
          background: "rgba(255, 253, 248, 0.84)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ ...mono, fontSize: 18, fontWeight: 800 }}>
            codingrabbit<span style={{ color: D.orange }}>.dev</span>
          </span>
          <span style={{ fontSize: 18 }}>🐇</span>
          <Tag>Beta</Tag>
        </div>
        <Btn onClick={handleLogin} disabled={hasOriginMismatch()}>
          Login →
        </Btn>
      </nav>

      {hasOriginMismatch() && (
        <div
          style={{
            margin: "12px 48px 0",
            padding: "12px 16px",
            background: `${D.orange}10`,
            border: `1px solid ${D.orangeBorder}`,
            borderRadius: 16,
            fontSize: 13,
            lineHeight: 1.6,
            boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)",
          }}
        >
          <strong>Wrong URL for Cognito login.</strong> Open the app at{" "}
          <a href={getRedirectOrigin()} style={{ color: D.orange }}>
            {getRedirectOrigin()}
          </a>{" "}
          (configured callback: <code>{getRedirectUri()}</code>). You are on{" "}
          <code>{window.location.origin}</code>.
        </div>
      )}

      <section style={{ padding: "64px 48px 36px", maxWidth: 1180, margin: "0 auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: 28,
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ marginBottom: 18 }}>
              <Tag>Gentle C++ tutoring for stressed humans</Tag>
            </div>
            <h1
              style={{
                fontSize: "clamp(42px, 6vw, 68px)",
                fontWeight: 800,
                margin: "0 0 16px",
                lineHeight: 1.02,
                letterSpacing: -2,
              }}
            >
              Hop into C++ with your
              <br />
              personal AI TA.
            </h1>
            <p
              style={{
                color: D.muted,
                fontSize: 18,
                lineHeight: 1.8,
                maxWidth: 620,
                margin: "0 0 26px",
              }}
            >
              CodingRabbit watches your code, respects your course material, and asks
              helpful questions until the answer clicks. It feels like a supportive
              office hour, not a cold debugger.
            </p>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
              <Btn onClick={handleLogin} disabled={hasOriginMismatch()}>
                Sign in to the app
              </Btn>
              {demoMode ? (
                <Btn
                  variant="ghost"
                  onClick={() => onNavigate("student")}
                  style={{ paddingLeft: 18, paddingRight: 18 }}
                >
                  Explore the student flow
                </Btn>
              ) : (
                <span
                  style={{
                    alignSelf: "center",
                    color: D.muted,
                    fontSize: 13,
                  }}
                >
                  Public sign-in only in this build
                </span>
              )}
            </div>

            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 10,
                alignItems: "center",
                color: D.muted,
                fontSize: 13,
              }}
            >
              {quickFacts.map((fact) => (
                <span
                  key={fact}
                  style={{
                    padding: "7px 10px",
                    borderRadius: 999,
                    background: "#FFFFFF",
                    border: `1px solid ${D.border}`,
                    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)",
                  }}
                >
                  {fact}
                </span>
              ))}
            </div>
          </div>

          <Card
            style={{
              padding: 0,
              overflow: "hidden",
              background:
                "linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(255,247,236,0.98) 100%)",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(180px, 0.95fr) minmax(0, 1.05fr)",
                gap: 16,
                alignItems: "center",
                padding: 24,
              }}
            >
              <div style={{ textAlign: "center" }}>
                <img
                  src={rabbitMascot}
                  alt="Coding Rabbit mascot"
                  style={{
                    width: "100%",
                    maxWidth: 260,
                    display: "block",
                    margin: "0 auto",
                    filter: "drop-shadow(0 18px 30px rgba(249, 115, 22, 0.12))",
                  }}
                />
                <div style={{ marginTop: 12 }}>
                  <Tag color={D.blue}>Meet CodeRabbit</Tag>
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div
                  style={{
                    background: "#EFF6FF",
                    border: "1px solid rgba(37, 99, 235, 0.16)",
                    borderRadius: 18,
                    padding: "12px 14px",
                    boxShadow: "0 10px 20px rgba(37, 99, 235, 0.06)",
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 800, color: D.blue, marginBottom: 4 }}>
                    Student
                  </div>
                  <div style={{ lineHeight: 1.7 }}>
                    Why does this loop skip the last element?
                  </div>
                </div>
                <div
                  style={{
                    background: "#FFF7ED",
                    border: "1px solid rgba(249, 115, 22, 0.16)",
                    borderRadius: 18,
                    padding: "12px 14px",
                    boxShadow: "0 10px 20px rgba(249, 115, 22, 0.06)",
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 800, color: D.orange, marginBottom: 4 }}>
                    CodingRabbit
                  </div>
                  <div style={{ lineHeight: 1.7 }}>
                    Let&apos;s trace the boundary together. What value does the loop
                    condition compare against on the final pass?
                  </div>
                </div>
                <div
                  style={{
                    background: "#FFFFFF",
                    border: `1px solid ${D.border}`,
                    borderRadius: 18,
                    padding: "12px 14px",
                    boxShadow: "0 10px 20px rgba(15, 23, 42, 0.04)",
                  }}
                >
                  <div style={{ fontSize: 12, color: D.muted, marginBottom: 8 }}>
                    What the rabbit keeps in mind
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {[
                      "Course-approved context only",
                      "Guardrails before and after the model",
                      "Hints over handouts",
                    ].map((item) => (
                      <div
                        key={item}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          color: D.text,
                          fontSize: 13,
                        }}
                      >
                        <span style={{ color: D.green }}>✓</span>
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </section>

      <section style={{ padding: "16px 48px 88px", maxWidth: 1180, margin: "0 auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 16,
          }}
        >
          {featureCards.map((feature) => (
            <Card key={feature.title} style={{ padding: 20 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginBottom: 12,
                }}
              >
                <span style={{ fontSize: 20 }}>{feature.icon}</span>
                <Tag color={feature.color}>{feature.tag}</Tag>
              </div>
              <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 8, lineHeight: 1.3 }}>
                {feature.title}
              </div>
              <div style={{ color: D.muted, fontSize: 14, lineHeight: 1.7 }}>
                {feature.desc}
              </div>
            </Card>
          ))}
        </div>

        {demoMode && (
          <div style={{ marginTop: 20 }}>
            <Card style={{ padding: 18 }}>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  justifyContent: "center",
                  flexWrap: "wrap",
                }}
              >
                {[
                  {
                    label: "Student interface",
                    view: "student" as const,
                    desc: "Codespaces + VS Code extension",
                  },
                  {
                    label: "Professor dashboard",
                    view: "professor" as const,
                    desc: "Class and material management",
                  },
                  {
                    label: "Admin panel",
                    view: "admin" as const,
                    desc: "Models, RAG, users, courses",
                  },
                ].map((r) => (
                  <button
                    key={r.view}
                    type="button"
                    onClick={() => onNavigate(r.view)}
                    onMouseEnter={() => setHover(r.view)}
                    onMouseLeave={() => setHover(null)}
                    style={{
                      background: hover === r.view ? D.orangeGlow : "#FFFFFF",
                      border: `1px solid ${hover === r.view ? D.orangeBorder : D.border}`,
                      borderRadius: 16,
                      padding: "12px 18px",
                      cursor: "pointer",
                      textAlign: "left",
                      transition: "all 0.15s ease",
                      minWidth: 220,
                      boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)",
                    }}
                  >
                    <div
                      style={{
                        color: hover === r.view ? D.orange : D.text,
                        fontWeight: 800,
                        fontSize: 14,
                      }}
                    >
                      → {r.label}
                    </div>
                    <div style={{ color: D.muted, fontSize: 12, marginTop: 4 }}>{r.desc}</div>
                  </button>
                ))}
              </div>
            </Card>
          </div>
        )}
      </section>
    </div>
  );
}
