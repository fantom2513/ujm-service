import { test } from "node:test";
import assert from "node:assert/strict";
import { parseFeedbackEntry } from "../../../src/services/feedback/index.ts";

test("parseFeedbackEntry: valid rating payload", () => {
  const entry = parseFeedbackEntry({ messageId: "msg-1", kind: "rating", value: "up" });
  assert.ok(entry);
  assert.equal(entry.messageId, "msg-1");
  assert.equal(entry.kind, "rating");
  assert.equal(entry.value, "up");
  assert.ok(typeof entry.timestamp === "string" && entry.timestamp.length > 0);
});

test("parseFeedbackEntry: valid copy payload has no value", () => {
  const entry = parseFeedbackEntry({ messageId: "msg-2", kind: "copy" });
  assert.ok(entry);
  assert.equal(entry.kind, "copy");
  assert.equal(entry.value, undefined);
});

test("parseFeedbackEntry: rejects missing messageId", () => {
  const entry = parseFeedbackEntry({ kind: "rating", value: "up" });
  assert.equal(entry, null);
});

test("parseFeedbackEntry: rejects unknown kind", () => {
  const entry = parseFeedbackEntry({ messageId: "msg-1", kind: "bogus", value: "up" });
  assert.equal(entry, null);
});

test("parseFeedbackEntry: rejects rating without a valid value", () => {
  const entry = parseFeedbackEntry({ messageId: "msg-1", kind: "rating" });
  assert.equal(entry, null);
  const entry2 = parseFeedbackEntry({ messageId: "msg-1", kind: "rating", value: "sideways" });
  assert.equal(entry2, null);
});
