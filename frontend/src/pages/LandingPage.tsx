import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { Btn, Card, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import type { AppView } from "../types/navigation";

interface LandingPageProps {
  onNavigate: (view: AppView) => void;
  demoMode?: boolean;
}

export function LandingPage({ onNavigate, demoMode = false }: LandingPageProps) {
  const auth = useAuth();
  const [hover, setHover] = useState<string | null>(null);

  const handleLogin = () => {
    if (demoMode) {
      onNavigate("student");
      return;
    }
    void auth.signinRedirect();
  };

  return (
    <div
      style={{
        background: D.bg,
        color: D.text,
        fontFamily: "system-ui, sans-serif",
        minHeight: "100vh",
        overflowY: "auto",
      }}
    >
      <nav
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 48px",
          height: 60,
          borderBottom: `1px solid ${D.border}`,
          position: "sticky",
          top: 0,
          background: D.bg,
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ ...mono, fontSize: 18, fontWeight: 700 }}>
            codingrabbit<span style={{ color: D.orange }}>.dev</span>
          </span>
          <span style={{ fontSize: 16 }}>🐇</span>
          <Tag>Beta</Tag>
        </div>
        <Btn onClick={handleLogin}>Login →</Btn>
      </nav>

      <section
        style={{
          padding: "68px 48px 52px",
          maxWidth: 980,
          margin: "0 auto",
          textAlign: "center",
        }}
      >
        <div style={{ marginBottom: 18 }}>
          <Tag>Socratic AI Tutor · CS Education · Phase 1</Tag>
        </div>

        <h1
          style={{
            fontSize: 52,
            fontWeight: 700,
            margin: "0 0 16px",
            lineHeight: 1.1,
            letterSpacing: -1.5,
            color: D.text,
          }}
        >
          The AI tutor that <span style={{ color: D.orange }}>asks</span>
          <br />
          before it answers.
        </h1>
        <p
          style={{
            color: D.muted,
            fontSize: 16,
            lineHeight: 1.8,
            maxWidth: 540,
            margin: "0 auto 48px",
          }}
        >
          CodingRabbit watches your code, detects where you&apos;re stuck, and leads
          you to the answer with questions — never handouts. Built for C++ courses,
          backed by your professor&apos;s approved material.
        </p>

        <div
          style={{
            background: D.surface,
            border: `1px solid ${D.border}`,
            borderRadius: 12,
            overflow: "hidden",
            textAlign: "left",
            marginBottom: 48,
            maxWidth: 780,
            margin: "0 auto 48px",
          }}
        >
          <div
            style={{
              background: D.card,
              padding: "9px 14px",
              borderBottom: `1px solid ${D.border}`,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {[D.red, D.yellow, D.green].map((c, i) => (
              <div
                key={i}
                style={{ width: 10, height: 10, borderRadius: "50%", background: c }}
              />
            ))}
            <span style={{ ...mono, fontSize: 11, color: D.muted, marginLeft: 10 }}>
              session@codingrabbit:~/cs101 — bash
            </span>
          </div>

          <div style={{ padding: "22px 28px", display: "flex", gap: 36 }}>
            <pre
              style={{
                ...mono,
                fontSize: 13,
                lineHeight: 1.58,
                margin: 0,
                color: D.text,
                flexShrink: 0,
              }}
            >{`
  /\\_/\\
 ( ^.^ )   "Don't panic."
  > 🥕 <
 /|   |\\   I'm CodeRabbit.
   | |
   |_|     I won't give
           you the answer.

           But I'll help
           you find it.`}</pre>

            <div style={{ flex: 1, ...mono, fontSize: 12.5, lineHeight: 1.65 }}>
              <div style={{ color: D.muted, marginBottom: 10 }}>
                <span style={{ color: D.orange }}>$ </span>./codingrabbit --attach main.cpp
              </div>
              <div>
                <span style={{ color: D.blue }}>#include </span>
                <span style={{ color: D.green }}>&lt;wisdom.h&gt;</span>
                <br />
                <span style={{ color: D.blue }}>#include </span>
                <span style={{ color: D.green }}>&lt;patience.h&gt;</span>
                <br />
                <br />
                <span style={{ color: D.purple }}>int </span>
                <span style={{ color: D.text }}>learn</span>
                <span style={{ color: D.muted }}>(Student&amp; s) {"{"}</span>
                <br />
                <span style={{ color: D.muted }}>{"  "}</span>
                <span style={{ color: D.blue }}>while </span>
                <span style={{ color: D.muted }}>(s.confused()) {"{"}</span>
                <br />
                <span style={{ color: D.dim }}>{"    "}s.question = </span>
                <span style={{ color: D.orange }}>rabbit.ask</span>
                <span style={{ color: D.muted }}>(s.code);</span>
                <br />
                <span style={{ color: "#4B5563" }}>
                  {"    "}s.think(); // ← most important step
                </span>
                <br />
                <span style={{ color: D.muted }}>{"  }"}</span>
                <br />
                <span style={{ color: D.blue }}>{"  "}return </span>
                <span style={{ color: D.text }}>s.understanding;</span>
                <br />
                <span style={{ color: D.muted }}>{"}"}</span>
              </div>
              <div style={{ marginTop: 14, color: D.green, fontSize: 12 }}>
                ✓ Attached · monitoring for errors and confusion signals...
              </div>
            </div>
          </div>
        </div>

        {demoMode && (
          <div
            style={{
              display: "flex",
              gap: 10,
              justifyContent: "center",
              flexWrap: "wrap",
            }}
          >
            {[
              { label: "Student interface", view: "student" as const, desc: "Monaco editor + AI chat" },
              { label: "Professor dashboard", view: "professor" as const, desc: "Class & material management" },
              { label: "Admin panel", view: "admin" as const, desc: "Models, RAG, users, courses" },
            ].map((r) => (
              <button
                key={r.view}
                type="button"
                onClick={() => onNavigate(r.view)}
                onMouseEnter={() => setHover(r.view)}
                onMouseLeave={() => setHover(null)}
                style={{
                  background: hover === r.view ? D.orangeGlow : "transparent",
                  border: `1px solid ${hover === r.view ? D.orangeBorder : D.border}`,
                  borderRadius: 8,
                  padding: "12px 22px",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "all 0.15s",
                }}
              >
                <div
                  style={{
                    color: hover === r.view ? D.orange : D.text,
                    fontWeight: 500,
                    fontSize: 13,
                  }}
                >
                  → {r.label}
                </div>
                <div style={{ color: D.muted, fontSize: 11, marginTop: 3 }}>{r.desc}</div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section style={{ padding: "8px 48px 80px", maxWidth: 980, margin: "0 auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 14,
          }}
        >
          {[
            {
              icon: "🤔",
              tag: "Core Method",
              tc: D.orange,
              title: "Socratic, not prescriptive",
              desc: "CodeRabbit reads your code and compiler errors, then asks guided questions until the insight is yours — not handed to you.",
            },
            {
              icon: "📊",
              tag: "For Professors",
              tc: D.blue,
              title: "Live class insight",
              desc: "See exactly where your class gets stuck, who's ahead, which concepts need re-teaching — all in one dashboard.",
            },
            {
              icon: "🔒",
              tag: "Curriculum-gated",
              tc: D.green,
              title: "No leaking ahead",
              desc: "The AI only accesses material your professor has approved and released. Week 3 stays locked until Week 3.",
            },
          ].map((f) => (
            <Card key={f.title} style={{ padding: "20px 18px" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginBottom: 12,
                }}
              >
                <span style={{ fontSize: 20 }}>{f.icon}</span>
                <Tag color={f.tc}>{f.tag}</Tag>
              </div>
              <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 8 }}>{f.title}</div>
              <div style={{ color: D.muted, fontSize: 13, lineHeight: 1.65 }}>{f.desc}</div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
