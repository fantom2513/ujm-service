import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import {
  _inlineRefs,
  _stripThinkTags,
  _extractMermaid,
  _extractJson,
  VLLMClient,
} from "../../../src/infrastructure/llm/client.ts";
import { LLMError } from "../../../src/infrastructure/llm/errors.ts";

test("_inlineRefs: no refs → passthrough (drops $defs)", () => {
  const schema = { type: "object", properties: { a: { type: "string" } } };
  assert.deepEqual(_inlineRefs(schema, {}), schema);
});

test("_inlineRefs: inlines $ref", () => {
  const defs = { Foo: { type: "string" } };
  const schema = { type: "object", $defs: defs, properties: { x: { "$ref": "#/$defs/Foo" } } };
  const result = _inlineRefs(schema, defs) as Record<string, unknown>;
  assert.equal((result.properties as Record<string, unknown>)["x"] as unknown, defs.Foo);
  assert.ok(!("$defs" in result));
});

test("_inlineRefs: nested $ref in array", () => {
  const defs = { Tag: { type: "string" } };
  const schema = { type: "object", properties: { tags: { type: "array", items: { "$ref": "#/$defs/Tag" } } } };
  const result = _inlineRefs(schema, defs) as Record<string, unknown>;
  const tags = (result.properties as Record<string, unknown>)["tags"] as Record<string, unknown>;
  assert.deepEqual(tags.items, { type: "string" });
});

test("_stripThinkTags: removes think block", () => {
  assert.equal(
    _stripThinkTags("<think>let me reason</think>\nflowchart LR\nA --> B"),
    "flowchart LR\nA --> B",
  );
});

test("_stripThinkTags: no tags → unchanged", () => {
  assert.equal(_stripThinkTags("flowchart LR\nA --> B"), "flowchart LR\nA --> B");
});

test("_extractMermaid: finds flowchart LR", () => {
  const input = "Sure!\n```mermaid\nflowchart LR\nA --> B\n```";
  assert.ok(_extractMermaid(input).startsWith("flowchart LR"));
});

test("_extractMermaid: finds flowchart TB without fences", () => {
  const input = "Here you go:\nflowchart TB\nA --> B";
  assert.ok(_extractMermaid(input).startsWith("flowchart TB"));
});

test("_extractMermaid: throws EMPTY_RESPONSE when no flowchart", () => {
  let err: unknown;
  try {
    _extractMermaid("no diagram here");
  } catch (e) {
    err = e;
  }
  assert.ok(err instanceof Error);
  const asErr = err as Error & { code?: string };
  assert.ok(asErr.message.includes("EMPTY_RESPONSE") || asErr.code === "EMPTY_RESPONSE");
});

test("_extractJson: parses clean JSON", () => {
  const result = _extractJson('{"mermaid":"flowchart LR\\nA-->B","message":"done"}');
  assert.equal(result["mermaid"], "flowchart LR\nA-->B");
  assert.equal(result["message"], "done");
});

test("_extractJson: skips leading text", () => {
  const result = _extractJson('Sure: {"mermaid":"x","message":"y"}');
  assert.equal(result["mermaid"], "x");
});

test("_extractJson: handles trailing text", () => {
  const result = _extractJson('{"a":"b"} extra text here');
  assert.equal(result["a"], "b");
});

test("_extractJson: throws INVALID_JSON when no JSON", () => {
  let err: unknown;
  try {
    _extractJson("no json here");
  } catch (e) {
    err = e;
  }
  assert.equal((err as { code?: string }).code, "INVALID_JSON");
});

// ─── HTTP layer (Task 3) ─────────────────────────────────────────────────────

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

test("completeText: returns Mermaid from LLM response", async () => {
  const { url, close } = mockLlmServer(llmResponse("flowchart LR\nA --> B"));
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    const result = await client.completeText("make a diagram");
    assert.ok(result.startsWith("flowchart LR"));
  } finally { close(); }
});

test("completeText: strips think tags before extracting", async () => {
  const { url, close } = mockLlmServer(
    llmResponse("<think>reasoning</think>\nflowchart TB\nA --> B"),
  );
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    const result = await client.completeText("make a diagram");
    assert.ok(result.startsWith("flowchart TB"));
    assert.ok(!result.includes("<think>"));
  } finally { close(); }
});

test("completeText: throws TIMEOUT when server too slow", async () => {
  const server = createServer(() => { /* never respond */ });
  server.listen(0);
  const { port } = server.address() as AddressInfo;
  try {
    const client = new VLLMClient({
      url: `http://127.0.0.1:${port}`,
      model: "test",
      timeoutMs: 50,
      responseFormatMode: "none",
    });
    const err = await client.completeText("test").catch((e) => e) as LLMError;
    assert.equal(err.code, "TIMEOUT");
  } finally { server.close(); }
});

test("completeJson: parses JSON response with json_schema mode", async () => {
  const payload = { mermaid: "flowchart LR\nA --> B", message: "done" };
  const { url, close } = mockLlmServer(llmResponse(JSON.stringify(payload)));
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "json_schema" });
    const schema = {
      type: "object",
      properties: { mermaid: { type: "string" }, message: { type: "string" } },
      required: ["mermaid", "message"],
    };
    const result = await client.completeJson("edit diagram", schema, "ChatOutput");
    assert.equal(result["mermaid"], payload.mermaid);
    assert.equal(result["message"], payload.message);
  } finally { close(); }
});

test("completeJson: throws STRUCTURED_OUTPUT_UNSUPPORTED on 422", async () => {
  const { url, close } = mockLlmServer({ error: "unsupported" }, 422);
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "json_schema" });
    const err = await client.completeJson("x", {}, "X").catch((e) => e) as LLMError;
    assert.equal(err.code, "STRUCTURED_OUTPUT_UNSUPPORTED");
  } finally { close(); }
});

test("completeJson: uses reasoning_content when content empty", async () => {
  const payload = { mermaid: "flowchart LR\nA-->B", message: "ok" };
  const { url, close } = mockLlmServer({
    choices: [{ message: { content: "", reasoning_content: JSON.stringify(payload) } }],
  });
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    const result = await client.completeJson("x", {}, "X");
    assert.equal(result["mermaid"], payload.mermaid);
  } finally { close(); }
});

test("completeJson: exposes usage from response on client.lastUsage", async () => {
  const payload = { mermaid: "flowchart LR\nA-->B", message: "ok" };
  const { url, close } = mockLlmServer({
    choices: [{ message: { content: JSON.stringify(payload) } }],
    usage: { prompt_tokens: 120, completion_tokens: 30, total_tokens: 150 },
  });
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    await client.completeJson("x", {}, "X");
    assert.deepEqual(client.lastUsage, { promptTokens: 120, completionTokens: 30, totalTokens: 150 });
  } finally { close(); }
});

test("completeText: usage is undefined when response omits it", async () => {
  const { url, close } = mockLlmServer(llmResponse("flowchart LR\nA --> B"));
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    await client.completeText("make a diagram");
    assert.equal(client.lastUsage, undefined);
  } finally { close(); }
});
