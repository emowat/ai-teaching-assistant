import { D, mono } from "../design/tokens";
import type { RunResult } from "../api/runApi";

interface ConsolePanelProps {
  result: RunResult | null;
  loading?: boolean;
  error?: string | null;
}

export function ConsolePanel({ result, loading, error }: ConsolePanelProps) {
  const compile = result?.compile;
  const ok = compile?.success ?? false;

  return (
    <div
      style={{
        borderTop: "1px solid #111",
        background: "#1a1a1a",
        display: "flex",
        flexDirection: "column",
        minHeight: 160,
        maxHeight: 220,
        flexShrink: 0,
      }}
    >
      <div
        style={{
          padding: "6px 12px",
          borderBottom: "1px solid #252526",
          display: "flex",
          alignItems: "center",
          gap: 10,
          ...mono,
          fontSize: 11,
          color: D.muted,
        }}
      >
        <span style={{ color: D.text }}>Compiler output</span>
        {loading && <span>Compiling...</span>}
        {!loading && compile && (
          <>
            <span style={{ color: ok ? D.green : D.red }}>
              {ok ? "✓ build succeeded" : "✗ build failed"}
            </span>
            {compile.exit_code !== null && (
              <span>exit {compile.exit_code}</span>
            )}
            <span>{compile.duration_ms}ms</span>
          </>
        )}
      </div>

      <pre
        style={{
          flex: 1,
          margin: 0,
          padding: "10px 14px",
          overflow: "auto",
          ...mono,
          fontSize: 12,
          lineHeight: 1.55,
          color: error ? D.red : compile?.stderr ? "#fca5a5" : D.dim,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {loading && "Waiting for sandbox..."}
        {error && error}
        {!loading && !error && compile && (
          <>
            {compile.stderr}
            {compile.stdout}
            {!compile.stderr && !compile.stdout && (ok ? "No output." : "No compiler output.")}
          </>
        )}
        {!loading && !error && !compile && "Click Compile to build your code."}
      </pre>
    </div>
  );
}
