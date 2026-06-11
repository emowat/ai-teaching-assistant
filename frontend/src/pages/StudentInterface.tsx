import { lazy, Suspense, useState } from "react";
import { useAuth } from "react-oidc-context";
import { compileCode, type RunResult } from "../api/runApi";
import { ConsolePanel } from "../components/ConsolePanel";
import { FileExplorer } from "../components/FileExplorer";

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

const INITIAL_FILES: Record<string, string> = {
  "linked_list.cpp": LINKED_LIST_CPP,
  "main.cpp": '#include <iostream>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n',
};

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

function langFromFilename(name: string): string {
  if (name.endsWith(".cpp") || name.endsWith(".cc") || name.endsWith(".cxx")) return "cpp";
  if (name.endsWith(".h") || name.endsWith(".hpp")) return "cpp";
  if (name.endsWith(".py")) return "python";
  if (name.endsWith(".txt")) return "plaintext";
  return "plaintext";
}

export function StudentInterface({
  onNavigate,
  allowedViews,
  onSignOut,
}: StudentInterfaceProps) {
  const auth = useAuth();

  // --- workspace state ---
  const [files, setFiles] = useState<Record<string, string>>(INITIAL_FILES);
  const [activeFile, setActiveFile] = useState("linked_list.cpp");

  // --- compile state ---
  const [compileResult, setCompileResult] = useState<RunResult | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);

  // --- chat state ---
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");

  // --- file operations ---
  const handleSelectFile = (name: string) => setActiveFile(name);

  const handleAddFile = (name: string) => {
    setFiles((prev) => ({ ...prev, [name]: "" }));
    setActiveFile(name);
  };

  const handleDeleteFile = (name: string) => {
    setFiles((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    if (activeFile === name) {
      const remaining = Object.keys(files).filter((f) => f !== name);
      setActiveFile(remaining[0] ?? "");
    }
  };

  const handleFileChange = (value: string) => {
    setFiles((prev) => ({ ...prev, [activeFile]: value }));
  };

  // --- compile ---
  const handleCompile = () => {
    const token = auth.user?.access_token;
    if (!token) {
      setCompileError("Sign in to compile your code.");
      return;
    }
    setCompiling(true);
    setCompileError(null);
    void compileCode(files, token, { entrypoint: activeFile })
      .then((response) => {
        setCompileResult(response.result);
      })
      .catch((err: unknown) => {
        setCompileResult(null);
        setCompileError(err instanceof Error ? err.message : "Compile failed.");
      })
      .finally(() => setCompiling(false));
  };

  // --- chat ---
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

  const activeCode = files[activeFile] ?? "";
  const buildOk = compileResult?.compile.success ?? null;

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

      {/* IDE chrome bar */}
      <div
        style={{
          padding: "5px 16px",
          borderBottom: `1px solid ${D.border}`,
          display: "flex",
          alignItems: "center",
          gap: 12,
          background: "#1a1a1a",
          flexShrink: 0,
        }}
      >
        <Tag>CS101</Tag>
        <span style={{ ...mono, fontSize: 12, color: D.text }}>{activeFile}</span>
        {buildOk === false && (
          <span style={{ ...mono, fontSize: 11, color: D.red }}>● build failed</span>
        )}
        {buildOk === true && (
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

      {/* Main 3-column layout */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Left: file explorer */}
        <FileExplorer
          files={files}
          activeFile={activeFile}
          onSelectFile={handleSelectFile}
          onAddFile={handleAddFile}
          onDeleteFile={handleDeleteFile}
          projectName="cs101 / week-02"
        />

        {/* Center: editor + console */}
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
          {/* Tab bar */}
          <div
            style={{
              background: "#252526",
              borderBottom: "1px solid #1a1a1a",
              display: "flex",
              flexShrink: 0,
              overflowX: "auto",
            }}
          >
            {Object.keys(files).map((name) => {
              const isActive = name === activeFile;
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => setActiveFile(name)}
                  style={{
                    padding: "5px 16px",
                    fontSize: 12,
                    cursor: "pointer",
                    color: isActive ? "#ccc" : "#666",
                    background: isActive ? "#1e1e1e" : "#2d2d2d",
                    border: "none",
                    borderRight: "1px solid #1a1a1a",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                    ...mono,
                  }}
                >
                  {name}
                </button>
              );
            })}
          </div>

          {/* Monaco + console */}
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ flex: 1, minHeight: 0 }}>
              {activeFile ? (
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
                    key={activeFile}
                    value={activeCode}
                    onChange={handleFileChange}
                    language={langFromFilename(activeFile)}
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
                  No files. Create one with the + button.
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

        {/* Right: chat panel */}
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
                    borderRadius:
                      m.role === "user" ? "12px 12px 3px 12px" : "12px 12px 12px 3px",
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
