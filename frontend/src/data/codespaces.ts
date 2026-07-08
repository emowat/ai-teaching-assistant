export interface WeekLaunchConfig {
  id: string;
  label: string;
  repoUrl: string;
  templateUrl: string;
  defaultBranch: string;
  enabled: boolean;
}

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
    defaultBranch: "main",
    enabled: true,
  },
  {
    id: "week-2",
    label: "Week 2 — Arrays",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    defaultBranch: "main",
    enabled: true,
  },
  {
    id: "week-3",
    label: "Week 3 — Classes",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    defaultBranch: "main",
    enabled: false,
  },
  {
    id: "week-4",
    label: "Week 4 — Templates",
    repoUrl: globalRepoUrl,
    templateUrl: globalTemplateUrl,
    defaultBranch: "main",
    enabled: false,
  },
];

function parseGithubRepoPath(url: string): { owner: string; repo: string } | null {
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== "github.com") return null;
    const [owner, repo] = parsed.pathname.replace(/^\/+/, "").split("/");
    if (!owner || !repo) return null;
    return { owner, repo: repo.replace(/\.git$/, "") };
  } catch {
    return null;
  }
}

function appendBranchQuery(url: URL, branch: string): URL {
  if (branch.trim()) {
    url.searchParams.set("ref", branch.trim());
  }
  return url;
}

function buildCodespacesLaunchUrl(candidate: string, branch: string): string | null {
  if (!candidate) return null;

  if (candidate.startsWith("https://codespaces.new/")) {
    const url = new URL(candidate);
    return appendBranchQuery(url, branch).toString();
  }

  const repoPath = parseGithubRepoPath(candidate);
  if (repoPath) {
    const url = new URL(`https://codespaces.new/${repoPath.owner}/${repoPath.repo}`);
    url.searchParams.set("quickstart", "1");
    return appendBranchQuery(url, branch).toString();
  }

  return candidate;
}

export function getWeekLaunchUrl(config: WeekLaunchConfig): string {
  const candidate = config.templateUrl.trim() || config.repoUrl.trim();
  return getCodespacesFallbackUrl(config.defaultBranch, candidate);
}

export function isWeekLaunchReady(config: WeekLaunchConfig): boolean {
  return Boolean(config.repoUrl.trim() || config.templateUrl.trim());
}

export function getCodespacesFallbackUrl(branch = "", overrideCandidate = ""): string {
  const candidate =
    overrideCandidate.trim() ||
    globalTemplateUrl ||
    globalRepoUrl ||
    fallbackCodespacesUrl;

  return buildCodespacesLaunchUrl(candidate, branch) ?? fallbackCodespacesUrl;
}
