"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <div className="editor-loading">Loading editor…</div>,
});

function languageFor(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "typescript";
  if (lower.endsWith(".js") || lower.endsWith(".jsx")) return "javascript";
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".md")) return "markdown";
  if (lower.endsWith(".css") || lower.endsWith(".scss")) return "scss";
  if (lower.endsWith(".html")) return "html";
  if (lower.endsWith(".toml") || lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".rs")) return "rust";
  if (lower.endsWith(".go")) return "go";
  return "plaintext";
}

type Props = {
  path: string | null;
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
};

export function CodeEditor({ path, value, onChange, readOnly }: Props) {
  const language = useMemo(() => (path ? languageFor(path) : "plaintext"), [path]);

  if (!path) {
    return (
      <div className="editor-empty">
        <p>Open a file from the explorer</p>
      </div>
    );
  }

  return (
    <MonacoEditor
      key={path}
      height="100%"
      theme="vs-dark"
      language={language}
      value={value}
      path={path}
      onChange={(next) => onChange(next ?? "")}
      options={{
        readOnly: !!readOnly,
        minimap: { enabled: false },
        fontSize: 13,
        fontFamily: "var(--font-jetbrains), Consolas, monospace",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        wordWrap: "on",
        renderLineHighlight: "line",
        padding: { top: 12 },
      }}
    />
  );
}
