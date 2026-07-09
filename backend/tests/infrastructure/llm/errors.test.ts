import { test } from "node:test";
import assert from "node:assert/strict";
import { LLMError } from "../../../src/infrastructure/llm/errors.ts";

test("LLMError: has code, message, name", () => {
  const err = new LLMError("TIMEOUT", "timed out");
  assert.equal(err.code, "TIMEOUT");
  assert.equal(err.message, "timed out");
  assert.equal(err.name, "LLMError");
  assert.ok(err instanceof Error);
});

test("LLMError: stores cause", () => {
  const cause = new Error("root");
  const err = new LLMError("HTTP_ERROR", "bad", cause);
  assert.equal(err.cause, cause);
});
