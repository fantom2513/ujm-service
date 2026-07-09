import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { chatEdit } from "../../../src/services/openai/index.ts";
import { config } from "../../../src/config/index.ts";
import type { ChatPromptOptions } from "../../../src/services/openai/prompts.ts";

function mockLlmServer(
  handler: (body: unknown) => { content: string },
): { url: string; close: () => void } {
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      const parsed = raw ? JSON.parse(raw) : {};
      const { content } = handler(parsed);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ choices: [{ message: { content, role: "assistant" } }] }));
    });
  });
  server.listen(0);
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, close: () => server.close() };
}

function opts(overrides: Partial<ChatPromptOptions> = {}): ChatPromptOptions {
  return {
    sourceText: "some source",
    additionalDetails: "",
    currentMermaid: "flowchart LR\nA --> B",
    previousMermaid: undefined,
    actionType: "FREEFORM",
    userMessage: "add a node",
    attachmentContext: "",
    ...overrides
  };
}

test("chatEdit: happy path returns mermaid + message from valid JSON response", async () => {
  const { url, close } = mockLlmServer(() => ({
    content: JSON.stringify({ mermaid: "flowchart LR\nA --> B --> C", message: "Добавил узел C." })
  }));
  const originalUrl = config.llmUrl;
  const originalMode = config.llmResponseFormatMode;
  config.llmUrl = url;
  config.llmResponseFormatMode = "none";
  try {
    const result = await chatEdit(opts());
    assert.equal(result.mermaidCode, "flowchart LR\nA --> B --> C");
    assert.equal(result.message, "Добавил узел C.");
  } finally {
    close();
    config.llmUrl = originalUrl;
    config.llmResponseFormatMode = originalMode;
  }
});

test("chatEdit: invalid mermaid on first attempt triggers repair, repair succeeds", async () => {
  let callCount = 0;
  const { url, close } = mockLlmServer(() => {
    callCount += 1;
    if (callCount === 1) {
      // First call: completeJson response, invalid mermaid (missing flowchart prefix)
      return { content: JSON.stringify({ mermaid: "graph TD\nA --> B", message: "Готово." }) };
    }
    // Second call: repair via completeText, valid mermaid this time
    return { content: "flowchart LR\nA --> B" };
  });
  const originalUrl = config.llmUrl;
  const originalMode = config.llmResponseFormatMode;
  config.llmUrl = url;
  config.llmResponseFormatMode = "none";
  try {
    const result = await chatEdit(opts());
    assert.equal(result.mermaidCode, "flowchart LR\nA --> B");
    assert.equal(result.message, "Готово.");
    assert.equal(callCount, 2);
  } finally {
    close();
    config.llmUrl = originalUrl;
    config.llmResponseFormatMode = originalMode;
  }
});
