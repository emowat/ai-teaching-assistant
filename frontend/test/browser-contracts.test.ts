import assert from "node:assert/strict";
import test from "node:test";

import { API_BASE_URL } from "../src/api/client.ts";
import { professorSectionStudentsPath } from "../src/api/professorSectionsApi.ts";
import { sectionLaunchConfigPath } from "../src/api/sectionLaunchConfigsApi.ts";
import { studentBootstrapPath } from "../src/api/studentBootstrapApi.ts";
import {
  getAdminLlmConfig,
  restartBackend,
  saveAdminLlmConfig,
} from "../src/api/adminLlmApi.ts";
import {
  getCodespacesFallbackUrl,
  getWeekLaunchUrl,
  isWeekLaunchReady,
} from "../src/data/codespaces.ts";
import {
  pickDefaultLaunchId,
  pickDefaultSection,
} from "../src/data/studentLaunch.ts";

test("frontend API helpers keep the expected default backend base URL in Node", () => {
  assert.equal(API_BASE_URL, "http://localhost:8000");
  assert.equal(studentBootstrapPath, "/api/student/bootstrap");
});

test("student launch helpers prefer explicit defaults and enabled launch configs", () => {
  const bootstrap = {
    default_section_id: "mit14-fall-002",
    sections: [
      { section_id: "mit14-fall-001" },
      { section_id: "mit14-fall-002" },
    ],
  } as const;

  assert.equal(pickDefaultSection(bootstrap), "mit14-fall-002");
  assert.equal(
    pickDefaultSection({ default_section_id: null, sections: bootstrap.sections }),
    "mit14-fall-001",
  );

  assert.equal(
    pickDefaultLaunchId([
      { launch_id: "fallback", enabled: false },
      { launch_id: "codespaces", enabled: true },
    ] as const),
    "codespaces",
  );
  assert.equal(
    pickDefaultLaunchId([
      { launch_id: "fallback", enabled: false },
    ] as const),
    "fallback",
  );
});

test("codespaces helper builds a launch URL from repo and branch metadata", () => {
  const launchUrl = new URL(
    getWeekLaunchUrl({
      id: "week-1",
      label: "Week 1",
      repoUrl: "https://github.com/example/coding-rabbit",
      templateUrl: "",
      defaultBranch: "student-smoke",
      enabled: true,
    }),
  );

  assert.equal(launchUrl.origin, "https://codespaces.new");
  assert.equal(launchUrl.pathname, "/example/coding-rabbit");
  assert.equal(launchUrl.searchParams.get("quickstart"), "1");
  assert.equal(launchUrl.searchParams.get("ref"), "student-smoke");
  assert.equal(isWeekLaunchReady({
    id: "week-1",
    label: "Week 1",
    repoUrl: "https://github.com/example/coding-rabbit",
    templateUrl: "",
    defaultBranch: "student-smoke",
    enabled: true,
  }), true);
  assert.equal(
    getCodespacesFallbackUrl("student-smoke", "https://github.com/example/coding-rabbit"),
    launchUrl.toString(),
  );
});

test("professor-facing API helpers encode section identifiers safely", () => {
  assert.equal(
    professorSectionStudentsPath("mit14/fall-001"),
    "/professor/sections/mit14%2Ffall-001/students",
  );
  assert.equal(
    sectionLaunchConfigPath("mit14/fall-001"),
    "/professor/sections/mit14%2Ffall-001/launch-configs",
  );
});

test("admin LLM helpers call the versioned API routes", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: typeof input === "string" ? input : input.toString(),
      init,
    });

    return {
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
      text: async () => "",
    } as Response;
  }) as typeof fetch;

  try {
    await getAdminLlmConfig("token-a");
    await saveAdminLlmConfig(
      {
        rag: { provider: "openai", model: "gpt-5.4-mini" },
        chat: { provider: "ollama", model: "qwen3.5:9b" },
        openai_api_key: null,
        openai_base_url: "https://api.openai.com/v1",
      },
      "token-b",
    );
    await restartBackend("token-c");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0]?.url, "http://localhost:8000/api/admin/llm/config");
  assert.equal(calls[0]?.init?.method ?? "GET", "GET");
  assert.equal(calls[1]?.url, "http://localhost:8000/api/admin/llm/config");
  assert.equal(calls[1]?.init?.method, "POST");
  assert.equal(calls[2]?.url, "http://localhost:8000/api/admin/restart");
  assert.equal(calls[2]?.init?.method, "POST");
});
