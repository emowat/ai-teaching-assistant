import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";

interface CodeEditorProps {
  value: string;
  onChange?: (value: string) => void;
  language?: string;
  highlightLines?: Array<{ line: number; kind: "warning" | "error" }>;
}

export function CodeEditor({
  value,
  onChange,
  language = "cpp",
  highlightLines = [],
}: CodeEditorProps) {
  const handleMount: OnMount = (monacoEditor, monaco) => {
    const decorations: editor.IModelDeltaDecoration[] = highlightLines.map(
      ({ line, kind }) => ({
        range: new monaco.Range(line, 1, line, 1),
        options: {
          isWholeLine: true,
          className:
            kind === "error" ? "monaco-line-error" : "monaco-line-warning",
        },
      })
    );

    monacoEditor.createDecorationsCollection(decorations);
  };

  return (
    <Editor
      height="100%"
      language={language}
      theme="vs-dark"
      value={value}
      onChange={(next) => onChange?.(next ?? "")}
      onMount={handleMount}
      options={{
        fontSize: 13,
        fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
        lineHeight: 22,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        padding: { top: 8 },
        automaticLayout: true,
        tabSize: 4,
        wordWrap: "off",
        renderLineHighlight: "line",
        scrollbar: {
          verticalScrollbarSize: 10,
          horizontalScrollbarSize: 10,
        },
      }}
    />
  );
}
