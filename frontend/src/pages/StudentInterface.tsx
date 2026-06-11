import { useState } from "react";
import { Btn, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import { TopBar } from "../components/TopBar";
import type { AppView } from "../types/navigation";

interface StudentInterfaceProps {
  onNavigate: (view: AppView) => void;
  allowedViews: AppView[];
  onSignOut: () => void;
}

interface ChatMessage {
  role: "bot" | "user";
  content: string;
}

// STUB — replace with VS Code extension code context in Sprint 4
const codeLines = [
  { n: 1, text: "#include <iostream>", fg: D.blue },
  { n: 15, text: "    LinkedList() {}  // ← BUG: head never initialized", fg: "#FCD34D", bg: `${D.yellow}0C`, borderLeft: `2px solid ${D.yellow}` },
  { n: 19, text: "        newNode->next = head->next;  // ← SEGFAULT HERE", fg: "#FCA5A5", bg: `${D.red}14`, borderLeft: `2px solid ${D.red}` },
];

// STUB — replace with POST /tutor/respond in Sprint 1
const initialMessages: ChatMessage[] = [
  {
    role: "bot",
    content:
      "Hey! I can see you're working on `linked_list.cpp`. What are you trying to do right now?",
  },
  {
    role: "user",
    content: "I'm trying to implement insert() but I keep getting a segfault.",
  },
  {
    role: "bot",
    content:
      "Segfaults in linked list inserts almost always come from one of two places.\n\nLet me ask: the very first time you call insert() on a brand-new list, what is the value of this->head?",
  },
];

export function StudentInterface({
  onNavigate,
  allowedViews,
  onSignOut,
}: StudentInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");

  const send = () => {
    if (!input.trim()) return;
    const msg = input;
    setInput("");
    // STUB — Sprint 1: call askTutor() with Bearer token
    setMessages((m) => [
      ...m,
      { role: "user", content: msg },
      {
        role: "bot",
        content:
          "Right! So the fix is a single character. Can you find the constructor on line 15 and make head point to something that means 'nothing here yet' in C++?",
      },
    ]);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: D.bg,
        color: D.text,
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <TopBar
        view="student"
        onNavigate={onNavigate}
        allowedViews={allowedViews}
        onSignOut={onSignOut}
      />

      <div
        style={{
          padding: "5px 16px",
          borderBottom: `1px solid ${D.border}`,
          display: "flex",
          alignItems: "center",
          gap: 12,
          background: "#1a1a1a",
        }}
      >
        <Tag>CS101</Tag>
        <span style={{ ...mono, fontSize: 12, color: D.text }}>linked_list.cpp</span>
        <span style={{ ...mono, fontSize: 11, color: D.red }}>● 1 error</span>
        <div style={{ flex: 1 }} />
        <Tag color={D.muted}>Editor STUB</Tag>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <div
          style={{
            flex: 3,
            background: "#1e1e1e",
            overflow: "auto",
            borderRight: "1px solid #111",
          }}
        >
          <div style={{ background: "#252526", borderBottom: "1px solid #1a1a1a", display: "flex" }}>
            <div
              style={{
                padding: "5px 16px",
                fontSize: 12,
                color: "#ccc",
                background: "#1e1e1e",
                borderRight: "1px solid #1a1a1a",
                ...mono,
              }}
            >
              <span style={{ color: D.red, marginRight: 4 }}>●</span>
              linked_list.cpp
            </div>
          </div>
          <div style={{ padding: "8px 0", ...mono, fontSize: 12.5, lineHeight: 1.65 }}>
            {codeLines.map((l) => (
              <div
                key={l.n}
                style={{
                  display: "flex",
                  background: l.bg || "transparent",
                  borderLeft: l.borderLeft || "2px solid transparent",
                }}
              >
                <span
                  style={{
                    width: 44,
                    textAlign: "right",
                    paddingRight: 16,
                    color: "#3d3d3d",
                    fontSize: 11,
                    userSelect: "none",
                    flexShrink: 0,
                  }}
                >
                  {l.n}
                </span>
                <span style={{ color: l.fg, whiteSpace: "pre" }}>{l.text}</span>
              </div>
            ))}
            <div style={{ padding: "12px 60px", color: D.muted, fontSize: 11 }}>
              ... full file shown in VS Code extension (Sprint 4)
            </div>
          </div>
        </div>

        <div
          style={{
            flex: 2,
            display: "flex",
            flexDirection: "column",
            background: D.bg,
            minWidth: 0,
          }}
        >
          <div
            style={{
              padding: "10px 14px",
              borderBottom: `1px solid ${D.border}`,
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: D.surface,
            }}
          >
            <span style={{ fontSize: 16 }}>🐇</span>
            <span style={{ fontWeight: 500, fontSize: 14, ...mono }}>CodeRabbit</span>
            <div style={{ width: 6, height: 6, background: D.green, borderRadius: "50%" }} />
            <div style={{ flex: 1 }} />
            <Tag color={D.muted}>Chat STUB</Tag>
          </div>

          <div
            style={{
              flex: 1,
              overflow: "auto",
              padding: "14px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: m.role === "user" ? "flex-end" : "flex-start",
                }}
              >
                {m.role === "bot" && (
                  <span style={{ fontSize: 10, color: D.muted, marginBottom: 3, ...mono }}>
                    🐇 codingrabbit
                  </span>
                )}
                <div
                  style={{
                    maxWidth: "90%",
                    padding: "9px 13px",
                    borderRadius: m.role === "user" ? "12px 12px 3px 12px" : "12px 12px 12px 3px",
                    background: m.role === "user" ? D.orange : D.card,
                    border: m.role === "user" ? "none" : `1px solid ${D.border}`,
                    color: D.text,
                    fontSize: 13,
                    lineHeight: 1.6,
                    whiteSpace: "pre-line",
                  }}
                >
                  {m.content}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              padding: "10px 14px",
              borderTop: `1px solid ${D.border}`,
              display: "flex",
              gap: 8,
              alignItems: "flex-end",
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask CodeRabbit… (Enter to send)"
              rows={1}
              style={{
                flex: 1,
                background: D.card,
                border: `1px solid ${D.border}`,
                color: D.text,
                borderRadius: 8,
                padding: "8px 11px",
                fontSize: 13,
                resize: "none",
                fontFamily: "system-ui",
                lineHeight: 1.5,
                outline: "none",
                maxHeight: 100,
              }}
            />
            <Btn onClick={send} style={{ padding: "8px 14px", flexShrink: 0 }}>
              Send
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
