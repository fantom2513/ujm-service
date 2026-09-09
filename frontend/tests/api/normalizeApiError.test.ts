import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeApiError } from "../../src/api/errors.ts";

test("normalizeApiError: generate fallback for a non-API error", () => {
  const result = normalizeApiError(new Error("network down"), "generate");
  assert.equal(result.code, "diagram-generation");
  assert.equal(typeof result.message, "string");
});

test("normalizeApiError: chat fallback differs from generate fallback", () => {
  const chatResult = normalizeApiError(undefined, "chat");
  const generateResult = normalizeApiError(undefined, "generate");
  assert.equal(chatResult.code, "chat-message-failed");
  assert.notEqual(chatResult.message, generateResult.message);
});

test("normalizeApiError: preserves a valid ApiError as-is", () => {
  const apiError = { code: "file-required", message: "Необходимо прикрепить файл" };
  assert.deepEqual(normalizeApiError(apiError, "generate"), apiError);
  assert.deepEqual(normalizeApiError(apiError, "chat"), apiError);
});

test("normalizeApiError: rejects an error with a non-string code", () => {
  const malformed = { code: 500, message: "oops" };
  const result = normalizeApiError(malformed, "chat");
  assert.equal(result.code, "chat-message-failed");
});

test("normalizeApiError: rejects an error missing message", () => {
  const malformed = { code: "file-required" };
  const result = normalizeApiError(malformed, "generate");
  assert.equal(result.code, "diagram-generation");
});

test("normalizeApiError: preserves session errors from the chat API", () => {
  for (const code of ["session-required", "session-not-found"] as const) {
    const apiError = { code, message: "Session error" };
    assert.deepEqual(normalizeApiError(apiError, "chat"), apiError);
  }
});
