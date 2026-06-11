const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";

export interface CommandResult {
  success: boolean;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
  timed_out: boolean;
}

export interface RunResult {
  compile: CommandResult;
  run: CommandResult | null;
  tests: Record<string, unknown>[];
  summary: {
    compile_failed: boolean;
    passed: number;
    failed: number;
  };
}

export interface CompileResponse {
  job_id: string;
  status: "completed" | "failed";
  result: RunResult | null;
  message: string;
}

export async function compileCode(
  files: Record<string, string>,
  accessToken: string,
  options?: {
    entrypoint?: string;
    mode?: "compile" | "sample";
    stdin?: string;
    sessionId?: string;
  }
): Promise<CompileResponse> {
  const response = await fetch(`${BASE_URL}/run/compile`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      files,
      entrypoint: options?.entrypoint ?? "main.cpp",
      mode: options?.mode ?? "compile",
      stdin: options?.stdin ?? "",
      session_id: options?.sessionId,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Compile failed (${response.status}): ${text}`);
  }

  return response.json() as Promise<CompileResponse>;
}
