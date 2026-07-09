import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { generateDiagram } from "../../../src/services/openai/index.ts";
import { VLLMClient } from "../../../src/infrastructure/llm/client.ts";
import type { NormalizedSource } from "../../../src/types/index.ts";

function mockLlmServer(
  responseBody: unknown,
  statusCode = 200,
): { url: string; close: () => void } {
  const server = createServer((_req, res) => {
    res.writeHead(statusCode, { "Content-Type": "application/json" });
    res.end(JSON.stringify(responseBody));
  });
  server.listen(0);
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, close: () => server.close() };
}

function llmResponse(content: string) {
  return { choices: [{ message: { content, role: "assistant" } }] };
}

function source(text: string): NormalizedSource {
  return {
    type: "text-file",
    title: "Test source",
    text,
    description: "desc"
  };
}

test("generateDiagram: builds prompt from source text and returns Mermaid from LLM", async () => {
  const { url, close } = mockLlmServer(llmResponse("flowchart LR\nA --> B"));
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    const result = await generateDiagram(source("Some technical spec"), "extra details", client);
    assert.ok(result.startsWith("flowchart LR"));
  } finally { close(); }
});

test("generateDiagram: propagates LLMError when the LLM call keeps failing (no infinite hang)", async () => {
  const { url, close } = mockLlmServer({ error: "boom" }, 500);
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    await assert.rejects(() => generateDiagram(source("spec"), "", client));
  } finally { close(); }
});
