/** Gradio admin console mounted on the rag_eng service at `/gradio`. */
export function getGradioUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
  return `${base.replace(/\/$/, "")}/gradio`;
}

/**
 * Probe whether the Gradio UI responds.
 * Uses no-cors so a reachable backend counts as available without CORS headers.
 */
export async function checkGradioAvailable(): Promise<boolean> {
  try {
    await fetch(getGradioUrl(), { method: "GET", mode: "no-cors" });
    return true;
  } catch {
    return false;
  }
}
