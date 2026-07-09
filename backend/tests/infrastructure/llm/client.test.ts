import { test } from "node:test";
import assert from "node:assert/strict";
import {
  _inlineRefs,
  _stripThinkTags,
  _extractMermaid,
  _extractJson,
} from "../../../src/infrastructure/llm/client.ts";

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
