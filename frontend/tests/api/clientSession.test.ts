import { test } from "node:test";
import assert from "node:assert/strict";
import { sendChatMessage } from "../../src/api/client.ts";


test("sendChatMessage always sends the explicit sessionId", async () => {
  const originalFetch = globalThis.fetch;
  let receivedForm: FormData | undefined;

  globalThis.fetch = async (input, init) => {
    assert.equal(input, "api/chat");
    assert.equal(init?.method, "POST");
    receivedForm = init?.body as FormData;
    return new Response(
      JSON.stringify({
        ok: true,
        result: {
          sessionId: "server-session",
          mermaidCode: "flowchart LR\nA-->B",
          message: "Done"
        }
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  };

  try {
    const form = new FormData();
    form.set("message", "change diagram");

    const result = await sendChatMessage("server-session", form);

    assert.equal(receivedForm?.get("sessionId"), "server-session");
    assert.equal(receivedForm?.get("message"), "change diagram");
    assert.equal(result.sessionId, "server-session");
    assert.equal(result.mermaidCode, "flowchart LR\nA-->B");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
