import { API_BASE_URL } from "./client";

export type LlmProvider = "cohere" | "openai" | "ollama" | "sagemaker";

export interface LlmRouteConfig {
  provider: LlmProvider;
  model: string;
}

export interface AdminLlmConfig {
  rag: LlmRouteConfig;
  chat: LlmRouteConfig;
  openai_api_key_configured: boolean;
  openai_base_url: string;
  restart_command_configured: boolean;
}

export interface AdminLlmConfigUpdate {
  rag: LlmRouteConfig;
  chat: LlmRouteConfig;
  openai_api_key?: string | null;
  openai_base_url?: string | null;
}

export interface RestartResponse {
  success: boolean;
  scheduled: boolean;
  message: string;
}

async function adminFetch<T>(
  path: string,
  accessToken: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${await response.text()}`);
  }

  return response.json() as Promise<T>;
}

export function getAdminLlmConfig(accessToken: string): Promise<AdminLlmConfig> {
  return adminFetch<AdminLlmConfig>("/admin/llm/config", accessToken);
}

export function saveAdminLlmConfig(
  payload: AdminLlmConfigUpdate,
  accessToken: string
): Promise<AdminLlmConfig> {
  return adminFetch<AdminLlmConfig>("/admin/llm/config", accessToken, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function restartBackend(accessToken: string): Promise<RestartResponse> {
  return adminFetch<RestartResponse>("/admin/restart", accessToken, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
