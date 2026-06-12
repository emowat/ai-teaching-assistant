export interface WeekLaunchConfig {
  id: string;
  label: string;
  repoUrl: string;
  templateUrl: string;
  enabled: boolean;
}

const storageKey = "codingrabbit.codespacesWeeks";
const fallbackCodespacesUrl =
  "https://github.com/codespaces/new?hide_repo_select=true&skip_quickstart=true";

const globalTemplateUrl = import.meta.env.VITE_CODESPACES_TEMPLATE_URL?.trim() ?? "";
const globalRepoUrl = import.meta.env.VITE_CODESPACES_REPO_URL?.trim() ?? "";

export const defaultWeekLaunchConfigs: WeekLaunchConfig[] = [
  {
    id: "week-1",
    label: "Week 1 — Pointers",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    enabled: true,
  },
  {
    id: "week-2",
    label: "Week 2 — Arrays",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    enabled: true,
  },
  {
    id: "week-3",
    label: "Week 3 — Classes",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    enabled: false,
  },
  {
    id: "week-4",
    label: "Week 4 — Templates",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    enabled: false,
  },
];

function readWeekLaunchConfigs(): WeekLaunchConfig[] | null {
  if (typeof window === "undefined") return null;

  const raw = window.localStorage.getItem(storageKey);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return null;

    return parsed
      .filter((item): item is WeekLaunchConfig => {
        if (!item || typeof item !== "object") return false;
        const candidate = item as WeekLaunchConfig;
        return (
          typeof candidate.id === "string" &&
          typeof candidate.label === "string" &&
          typeof candidate.repoUrl === "string" &&
          typeof candidate.templateUrl === "string" &&
          typeof candidate.enabled === "boolean"
        );
      })
      .map((item) => ({ ...item }));
  } catch {
    return null;
  }
}

export function loadWeekLaunchConfigs(): WeekLaunchConfig[] {
  const loaded = readWeekLaunchConfigs();
  if (!loaded || loaded.length === 0) return [...defaultWeekLaunchConfigs];
  return loaded;
}

export function saveWeekLaunchConfigs(configs: WeekLaunchConfig[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey, JSON.stringify(configs));
}

export function getWeekLaunchUrl(config: WeekLaunchConfig): string {
  return (
    config.templateUrl.trim() ||
    config.repoUrl.trim() ||
    globalTemplateUrl ||
    globalRepoUrl ||
    fallbackCodespacesUrl
  );
}

export function getDefaultWeekId(configs: WeekLaunchConfig[]): string {
  const enabled = configs.find((config) => config.enabled);
  return enabled?.id ?? configs[0]?.id ?? defaultWeekLaunchConfigs[0].id;
}
