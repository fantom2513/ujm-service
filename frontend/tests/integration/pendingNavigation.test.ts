import test from "node:test";
import assert from "node:assert/strict";
import { defaultState } from "../../src/state/session.ts";

async function waitUntil(check: () => boolean): Promise<void> {
  for (let i = 0; i < 100; i++) {
    if (check()) return;
    await new Promise<void>(resolve => setImmediate(resolve));
  }
  assert.ok(check(), "UI did not reach the expected state");
}

for (const kind of ["generate", "chat"] as const) {
  test(`popstate during ${kind} displays the completed result and clears pending state`, async () => {
    const originals = { window: globalThis.window, document: globalThis.document, storage: globalThis.sessionStorage, fetch: globalThis.fetch, error: console.error };
    const handlers = new Map<string, () => void>();
    const buttons = new Map<string, {addEventListener: (kind: string, listener: () => void) => void}>();
    const app = {innerHTML: ""};
    const values = new Map<string, string>();
    const initial = structuredClone(defaultState);
    if (kind === "chat") {
      initial.page = "result";
      initial.result = {sessionId: "s1", title: "Initial", mermaidCode: "flowchart LR\nA-->Old", sourceText: "Issue", sourceContext: {type: "link", title: "Issue", description: "Jira"}, chat: [], warnings: []};
      initial.pendingTurn = {kind: "chat", sessionId: "s1", requestId: "r1"};
    }
    initial.start.sourceType = "link"; initial.start.link = "https://jira.example.com/browse/ABC-1";
    values.set("copilot-mermaid-session-v1", JSON.stringify(initial));
    globalThis.sessionStorage = {
      getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); },
      removeItem: key => { values.delete(key); },
    } as Storage;
    const readState = () => JSON.parse(values.get("copilot-mermaid-session-v1")!);
    globalThis.document = {
      querySelector: (selector: string) => {
        if (selector === "#app") return app;
        if (selector === "#build") {
          if (!buttons.has(selector)) buttons.set(selector, {addEventListener: (_kind, listener) => { handlers.set("build", listener); }});
          return buttons.get(selector);
        }
        return null;
      },
      querySelectorAll: () => [], addEventListener: () => {}, removeEventListener: () => {},
    } as unknown as Document;
    globalThis.window = {
      addEventListener: (kind: string, listener: () => void) => { handlers.set(kind, listener); },
      requestAnimationFrame: () => 1, innerWidth: 1400, innerHeight: 900,
    } as unknown as Window & typeof globalThis;
    console.error = () => {};
    let finishOldPoll: (response: Response) => void;
    let polls = 0;
    const result = { sessionId: "s1", title: "Recovered", mermaidCode: "flowchart LR\nA-->B", message: "Done", sourceText: "Issue", sourceContext: {type: "link", title: "Issue", description: "Jira", url: initial.start.link}, chat: [], warnings: [] };
    globalThis.fetch = async (path, init) => {
      if (path === "api/config") return new Response(JSON.stringify({productHomeUrl: "https://example.com"}));
      if (init?.method === "POST") return new Response(JSON.stringify({status: "processing", sessionId: "s1", requestId: "r1"}), {status: 202});
      polls++;
      if (polls > 1) return new Response(JSON.stringify(result));
      return new Promise<Response>((resolve, reject) => {
        finishOldPoll = resolve;
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason), {once: true});
      });
    };
    try {
      await import(`../../src/main.ts?navigation-test-${kind}`);
      if (kind === "generate") handlers.get("build")!();
      await waitUntil(() => polls === 1);
      handlers.get("popstate")!();
      finishOldPoll!(new Response(JSON.stringify(result)));
      await waitUntil(() => readState().result?.mermaidCode === "flowchart LR\nA-->B" && !readState().pendingTurn);
      assert.equal(readState().result.sessionId, "s1");
      assert.equal(readState().pendingTurn, undefined);
      if (kind === "chat") {
        assert.equal(readState().result.chat.length, 1);
        assert.equal(readState().result.chat[0].text, result.message);
        assert.doesNotMatch(app.innerHTML, /message-generating/);
      }
    } finally {
      globalThis.window = originals.window; globalThis.document = originals.document;
      globalThis.sessionStorage = originals.storage; globalThis.fetch = originals.fetch;
      console.error = originals.error;
    }
  });

}
