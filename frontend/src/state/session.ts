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

// getConfig() fetches productHomeUrl from the backend once, at startup, and
// state is never re-fetched after that. A plain structuredClone(defaultState)
// (used to reset the app for "new diagram" / "go home") would silently revert
// productHomeUrl to the hardcoded localhost fallback for the rest of the
// session -- carry the already-fetched config forward across every reset.
export function resetState(current: AppState): AppState {
  const next = structuredClone(defaultState);
  next.config = current.config;
  return next;
}

// A chat request is asynchronous; the user can start a new diagram before it
// resolves. state.result by then points at the new diagram, so a plain
// `!!state.result` check no longer catches a response that belongs to the
// diagram the user has already left -- compare sessionId instead.
export function isCurrentChatSession(
  state: AppState,
  sessionId: string
): state is AppState & { result: NonNullable<AppState["result"]> } {
  return state.result?.sessionId === sessionId;
}
