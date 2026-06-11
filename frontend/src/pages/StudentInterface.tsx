import { lazy, Suspense, useState } from "react";
import { useAuth } from "react-oidc-context";
import { compileCode, type RunResult } from "../api/runApi";
import { ConsolePanel } from "../components/ConsolePanel";

const CodeEditor = lazy(() =>
  import("../components/CodeEditor").then((m) => ({ default: m.CodeEditor }))
);
import { Btn, Tag } from "../design/atoms";
import { D, mono } from "../design/tokens";
import { TopBar } from "../components/TopBar";
import { LINKED_LIST_CPP } from "../demo/linkedListCpp";
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

const editorFiles = ["linked_list.cpp", "main.cpp"] as const;

export function StudentInterface({
  onNavigate,
  allowedViews,
  onSignOut,
}: StudentInterfaceProps) {
  const auth = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [code, setCode] = useState(LINKED_LIST_CPP);
  const [activeFile, setActiveFile] = useState<(typeof editorFiles)[number]>(
    "linked_list.cpp"
  );
  const [compileResult, setCompileResult] = useState<RunResult | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);

  const handleCompile = () => {
    const token = auth.user?.access_token;
    if (!token) {
      setCompileError("Sign in to compile your code.");
      return;
    }

    setCompiling(true);
    setCompileError(null);
    void compileCode(
      { [activeFile]: code },
      token,
      { entrypoint: activeFile }
    )
      .then((response) => {
        setCompileResult(response.result);
        if (!response.result?.compile.success) {
          setCompileError(null);
        }
      })
      .catch((err: unknown) => {
        setCompileResult(null);
        setCompileError(err instanceof Error ? err.message : "Compile failed.");
      })
      .finally(() => setCompiling(false));
  };

  const send = () => {
    if (!input.trim()) return;
    const msg = input;
    setInput("");
    // STUB — Sprint 1: call askTutor() with Bearer token + code context
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
        <span style={{ ...mono, fontSize: 12, color: D.text }}>{activeFile}</span>
        {compileResult && !compileResult.compile.success && (
          <span style={{ ...mono, fontSize: 11, color: D.red }}>● build failed</span>
        )}
        {compileResult?.compile.success && (
          <span style={{ ...mono, fontSize: 11, color: D.green }}>● build ok</span>
        )}
        <div style={{ flex: 1 }} />
        <Btn small onClick={handleCompile} disabled={compiling}>
          {compiling ? "Compiling…" : "Compile"}
        </Btn>
        <span style={{ ...mono, fontSize: 10, color: D.muted }}>
          Week 2 · Dynamic memory · C++17
        </span>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <div
          style={{
            flex: 3,
            display: "flex",
            flexDirection: "column",
            background: "#1e1e1e",
            borderRight: "1px solid #111",
            minWidth: 0,
          }}
        >
          <div
            style={{
              background: "#252526",
              borderBottom: "1px solid #1a1a1a",
              display: "flex",
              flexShrink: 0,
            }}
          >
            {editorFiles.map((file) => {
              const isActive = activeFile === file;
              return (
                <button
                  key={file}
                  type="button"
                  onClick={() => setActiveFile(file)}
                  style={{
                    padding: "5px 16px",
                    fontSize: 12,
                    cursor: "pointer",
                    color: isActive ? "#ccc" : "#666",
                    background: isActive ? "#1e1e1e" : "#2d2d2d",
                    border: "none",
                    borderRight: "1px solid #1a1a1a",
                    ...mono,
                  }}
                >
                  {file === "linked_list.cpp" && (
                    <span style={{ color: D.red, marginRight: 4 }}>●</span>
                  )}
                  {file}
                </button>
              );
            })}
          </div>

          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ flex: 1, minHeight: 0 }}>
            {activeFile === "linked_list.cpp" ? (
              <Suspense
                fallback={
                  <div
                    style={{
                      height: "100%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: D.muted,
                      fontSize: 13,
                      ...mono,
                    }}
                  >
                    Loading editor...
                  </div>
                }
              >
                <CodeEditor
                  value={code}
                  onChange={setCode}
                  language="cpp"
                  highlightLines={[
                    { line: 15, kind: "warning" },
                    { line: 19, kind: "error" },
                    { line: 35, kind: "error" },
                  ]}
                />
              </Suspense>
            ) : (
              <div
                style={{
                  height: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: D.muted,
                  fontSize: 13,
                  ...mono,
                }}
              >
                main.cpp — coming soon
              </div>
            )}
            </div>
            <ConsolePanel
              result={compileResult}
              loading={compiling}
              error={compileError}
            />
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
