import { test } from "node:test";
import assert from "node:assert/strict";
import { defaultState, loadState, saveState } from "../../src/state/session.ts";


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
