import { test } from "node:test";
import assert from "node:assert/strict";
import { defaultState, isCurrentChatSession, loadState, resetState, saveState } from "../../src/state/session.ts";


test("session storage keeps sessionId together with the diagram", () => {
  const originalStorage = globalThis.sessionStorage;
  const values = new Map<string, string>();
  globalThis.sessionStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    }
  };

  try {
    const state = structuredClone(defaultState);
    state.page = "result";
    state.result = {
      sessionId: "persisted-session",
      title: "Diagram",
      mermaidCode: "flowchart LR\nA-->B",
      sourceText: "spec",
      sourceContext: { type: "text-file", title: "spec", description: "text" },
      chat: [],
      warnings: []
    };

    saveState(state);

    assert.equal(loadState().result?.sessionId, "persisted-session");
    assert.equal(loadState().result?.mermaidCode, "flowchart LR\nA-->B");
  } finally {
    globalThis.sessionStorage = originalStorage;
  }
});

test("loadState clears a restored chat attachment because its File object cannot survive sessionStorage", () => {
  const originalStorage = globalThis.sessionStorage;
  const values = new Map<string, string>();
  globalThis.sessionStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    }
  };

  try {
    const state = structuredClone(defaultState);
    state.page = "result";
    state.result = {
      sessionId: "session-a",
      title: "Diagram",
      mermaidCode: "flowchart LR\nA-->B",
      sourceText: "spec",
      sourceContext: { type: "text-file", title: "spec", description: "text" },
      chat: [],
      warnings: []
    };
    state.chatAttachment = { name: "notes.txt", format: "txt", size: 10 };
    state.chatAttachments = [state.chatAttachment];

    saveState(state);
    const restored = loadState();

    assert.equal(restored.chatAttachment, undefined);
    assert.equal(restored.chatAttachments, undefined);
  } finally {
    globalThis.sessionStorage = originalStorage;
  }
});

test("resetState keeps the config fetched from the backend instead of the hardcoded default", () => {
  const current = structuredClone(defaultState);
  current.config.productHomeUrl = "https://real-product.example/";

  const next = resetState(current);

  assert.equal(next.config.productHomeUrl, "https://real-product.example/");
});

test("resetState still clears everything else back to defaultState", () => {
  const current = structuredClone(defaultState);
  current.config.productHomeUrl = "https://real-product.example/";
  current.page = "result";
  current.chatDraft = "unsent draft";

  const next = resetState(current);

  assert.equal(next.page, "start");
  assert.equal(next.chatDraft, "");
  assert.equal(next.result, undefined);
});

test("isCurrentChatSession is true when the result still matches the request's sessionId", () => {
  const state = structuredClone(defaultState);
  state.result = {
    sessionId: "session-a",
    title: "Diagram",
    mermaidCode: "flowchart LR\nA-->B",
    sourceText: "spec",
    sourceContext: { type: "text-file", title: "spec", description: "text" },
    chat: [],
    warnings: []
  };

  assert.equal(isCurrentChatSession(state, "session-a"), true);
});

test("isCurrentChatSession is false once the user has moved on to a different diagram", () => {
  const state = structuredClone(defaultState);
  state.result = {
    sessionId: "session-b",
    title: "Diagram B",
    mermaidCode: "flowchart LR\nC-->D",
    sourceText: "spec b",
    sourceContext: { type: "text-file", title: "spec b", description: "text" },
    chat: [],
    warnings: []
  };

  assert.equal(isCurrentChatSession(state, "session-a"), false);
});

test("isCurrentChatSession is false once the result has been cleared entirely", () => {
  const state = structuredClone(defaultState);
  state.result = undefined;

  assert.equal(isCurrentChatSession(state, "session-a"), false);
});
