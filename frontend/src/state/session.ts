import type { AppState } from "../types/index.ts";

const storageKey = "copilot-mermaid-session-v1";

export const defaultState: AppState = {
  page: "start",
  start: {
    sourceType: "text-file",
    link: "",
    details: ""
  },
  view: {
    scale: 1,
    x: 0,
    y: 0
  },
  chatDraft: "",
  config: {
    productHomeUrl: "http://localhost:3000/"
  }
};

export function loadState(): AppState {
  const raw = sessionStorage.getItem(storageKey);
  if (!raw) return structuredClone(defaultState);
  try {
    return { ...structuredClone(defaultState), ...JSON.parse(raw) };
  } catch {
    return structuredClone(defaultState);
  }
}

export function saveState(state: AppState): void {
  sessionStorage.setItem(storageKey, JSON.stringify(state));
}

export function clearState(): void {
  sessionStorage.removeItem(storageKey);
}
