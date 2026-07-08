import type { NormalizedSource } from "../../types/index.ts";

export function classifyWorkLink(value: string): "jira" | "confluence" | null {
  try {
    const url = new URL(value);
    const searchable = `${url.hostname}${url.pathname}`.toLowerCase();
    if (searchable.includes("jira")) return "jira";
    if (searchable.includes("confluence") || searchable.includes("wiki")) return "confluence";
    return null;
  } catch {
    return null;
  }
}

export function normalizeLink(value: string): NormalizedSource {
  const type = classifyWorkLink(value);
  const label = type === "jira" ? "Jira" : "Confluence";

  // Temporary integration point: replace this stub with real Jira/Confluence API access
  // after service URLs, credentials and supported link formats are approved.
  return {
    type: "link",
    title: `${label}: тестовый источник`,
    text: `Контролируемая заглушка ${label}. Здесь будет текст задачи или страницы после подключения серверной интеграции.`,
    description: `${label} · ${value}`,
    url: value,
    stub: true
  };
}
