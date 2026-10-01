import { test } from "node:test";
import assert from "node:assert/strict";
import { sendChatMessage } from "../../src/api/client.ts";


test("sendChatMessage sends sessionId without replacing requestId", async () => {
  const originalFetch = globalThis.fetch;
  let receivedForm: FormData | undefined;

  globalThis.fetch = async (input, init) => {
    assert.equal(input, "api/chat");
    assert.equal(init?.method, "POST");
    receivedForm = init?.body as FormData;
    return new Response(
      JSON.stringify({
        sessionId: "server-session",
        mermaidCode: "flowchart LR\nA-->B",
        message: "Done"
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  };

  try {
    const form = new FormData();
    form.set("message", "change diagram");
    form.set("requestId", "user-message-id");

    const result = await sendChatMessage("server-session", form);

    assert.equal(receivedForm?.get("sessionId"), "server-session");
    assert.equal(receivedForm?.get("requestId"), "user-message-id");
    assert.equal(receivedForm?.get("message"), "change diagram");
    assert.equal(result.sessionId, "server-session");
    assert.equal(result.mermaidCode, "flowchart LR\nA-->B");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("sendChatMessage polls a 202 request until its result is ready", async () => {
  const originalFetch = globalThis.fetch;
  const originalSetTimeout = globalThis.setTimeout;
  const calls: string[] = [];
  let accepted: { kind: string; sessionId: string; requestId: string } | undefined;
  globalThis.setTimeout = ((callback: () => void) => { queueMicrotask(callback); return 1; }) as typeof setTimeout;
  globalThis.fetch = async (input) => {
    calls.push(String(input));
    if (calls.length === 1) return new Response(JSON.stringify({ status: "processing", sessionId: "s-1", requestId: "r-1" }), { status: 202 });
    if (calls.length === 2) return new Response(JSON.stringify({ status: "processing" }), { status: 200 });
    return new Response(JSON.stringify({ sessionId: "s-1", mermaidCode: "flowchart LR\nA-->B", message: "Done" }), { status: 200 });
  };
  try {
    const form = new FormData();
    form.set("requestId", "r-1");
    const result = await sendChatMessage("s-1", form, (pending) => { accepted = pending; });
    assert.deepEqual(accepted, { kind: "chat", sessionId: "s-1", requestId: "r-1" });
    assert.deepEqual(calls, ["api/chat", "api/chat/s-1/turns/r-1", "api/chat/s-1/turns/r-1"]);
    assert.equal(result.message, "Done");
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.setTimeout = originalSetTimeout;
  }
});

test("polling survives a temporary network interruption", async () => {
  const originalFetch = globalThis.fetch;
  const originalSetTimeout = globalThis.setTimeout;
  let calls = 0;
  globalThis.setTimeout = ((callback: () => void) => { queueMicrotask(callback); return 1; }) as typeof setTimeout;
  globalThis.fetch = async () => {
    calls++;
    if (calls === 1) return new Response(JSON.stringify({ status: "processing", sessionId: "s-1", requestId: "r-1" }), { status: 202 });
    if (calls === 2) throw new TypeError("offline");
    if (calls === 3) return new Response("gateway unavailable", { status: 503 });
    return new Response(JSON.stringify({ sessionId: "s-1", mermaidCode: "flowchart LR\nA-->B", message: "Done" }), { status: 200 });
  };
  try {
    const form = new FormData();
    form.set("requestId", "r-1");
    const result = await sendChatMessage("s-1", form);
    assert.equal(result.message, "Done");
    assert.equal(calls, 4);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.setTimeout = originalSetTimeout;
  }
});
