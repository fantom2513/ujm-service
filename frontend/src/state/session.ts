import type { AppState } from "../types/index.ts";

const storageKey = "copilot-mermaid-session-v1";

export const defaultState: AppState = {
  page: "start",
  start: {
    sourceType: "text-file",
    link: "",
    details: ""
  },
  previousMermaidCode: undefined,
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
    const restored = { ...structuredClone(defaultState), ...JSON.parse(raw) };
    return clearUnrecoverableAttachment(restored);
  } catch {
    return structuredClone(defaultState);
  }
}

// File objects can't survive JSON.stringify, so a restored `start.file`/
// `start.recording` is metadata for a File that no longer exists in memory
// -- without this, the UI shows an attachment as if it's still attached
// (no error, no remove/retry action) while every submit silently fails
// "file-required". Clearing it here makes the UI honestly say "not
// attached" instead of looking recovered but being non-functional.
function clearUnrecoverableAttachment(state: AppState): AppState {
  if (state.start.file || state.start.recording) {
    state.start.file = undefined;
    state.start.recording = undefined;
    if (state.start.error?.field === "attachment") state.start.error = undefined;
  }
  return state;
}

export function saveState(state: AppState): void {
  sessionStorage.setItem(storageKey, JSON.stringify(state));
}

export function clearState(): void {
  sessionStorage.removeItem(storageKey);
}
