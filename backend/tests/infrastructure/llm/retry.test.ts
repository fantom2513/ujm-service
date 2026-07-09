import { test } from "node:test";
import assert from "node:assert/strict";
import { LLMError } from "../../../src/infrastructure/llm/errors.ts";
import { executeWithRetry, completeJsonWithFallback } from "../../../src/infrastructure/llm/retry.ts";
import { VLLMClient } from "../../../src/infrastructure/llm/client.ts";

test("executeWithRetry: returns value on first success", async () => {
  let calls = 0;
  const result = await executeWithRetry(async () => { calls++; return 42; });
  assert.equal(result, 42);
  assert.equal(calls, 1);
});

test("executeWithRetry: retries on TIMEOUT", async () => {
  let calls = 0;
  const result = await executeWithRetry(async () => {
    calls++;
    if (calls < 3) throw new LLMError("TIMEOUT", "timed out");
    return "ok";
  }, 3, 0, 0);
  assert.equal(result, "ok");
  assert.equal(calls, 3);
});

test("executeWithRetry: does NOT retry SCHEMA_MISMATCH", async () => {
  let calls = 0;
  const err = await executeWithRetry(async () => {
    calls++;
    throw new LLMError("SCHEMA_MISMATCH", "bad schema");
  }, 3, 0, 0).catch((e) => e) as LLMError;
  assert.equal(calls, 1);
  assert.equal(err.code, "SCHEMA_MISMATCH");
});

test("executeWithRetry: throws last error after exhausting retries", async () => {
  const err = await executeWithRetry(
    async () => { throw new LLMError("HTTP_ERROR", "bad"); },
    2, 0, 0,
  ).catch((e) => e) as LLMError;
  assert.equal(err.code, "HTTP_ERROR");
});

test("completeJsonWithFallback: falls back from json_schema to json_object on STRUCTURED_OUTPUT_UNSUPPORTED", async () => {
  const modes: string[] = [];
  const result = await completeJsonWithFallback(
    (mode) => {
      modes.push(mode);
      return {
        completeJson: async () => {
          if (mode === "json_schema") throw new LLMError("STRUCTURED_OUTPUT_UNSUPPORTED", "no");
          return { ok: true };
        },
      } as unknown as VLLMClient;
    },
    "json_schema",
    async (client) => client.completeJson("", {}, ""),
    2, 1,
  );
  assert.deepEqual(result, { ok: true });
  assert.ok(modes.includes("json_schema"));
  assert.ok(modes.includes("json_object"));
});

test("completeJsonWithFallback: does NOT fall back on HTTP_ERROR", async () => {
  const modes: string[] = [];
  const err = await completeJsonWithFallback(
    (mode) => {
      modes.push(mode);
      return {
        completeJson: async () => { throw new LLMError("HTTP_ERROR", "bad"); },
      } as unknown as VLLMClient;
    },
    "json_schema",
    async (client) => client.completeJson("", {}, ""),
    1, 1,
  ).catch((e) => e) as LLMError;
  assert.equal(err.code, "HTTP_ERROR");
  assert.equal(modes.length, 1);
});
