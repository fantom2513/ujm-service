import { test } from "node:test";
import assert from "node:assert/strict";
import { requiredSourceError } from "../../src/server/generateGuard.ts";

// #12 regression: /api/generate must reject requests with no usable source
// before it ever reaches the LLM ("silent generation" guard).

test("requiredSourceError: text-file without a file -> file-required", () => {
  assert.equal(
    requiredSourceError({ sourceType: "text-file", hasFile: false, link: "" }),
    "file-required"
  );
});

test("requiredSourceError: recording without a file -> file-required", () => {
  assert.equal(
    requiredSourceError({ sourceType: "recording", hasFile: false, link: "" }),
    "file-required"
  );
});

test("requiredSourceError: text-file with a file -> null (passes)", () => {
  assert.equal(
    requiredSourceError({ sourceType: "text-file", hasFile: true, link: "" }),
    null
  );
});

test("requiredSourceError: recording with a file -> null (passes)", () => {
  assert.equal(
    requiredSourceError({ sourceType: "recording", hasFile: true, link: "" }),
    null
  );
});

test("requiredSourceError: link without a link value -> link-required", () => {
  assert.equal(
    requiredSourceError({ sourceType: "link", hasFile: false, link: "" }),
    "link-required"
  );
});

test("requiredSourceError: link with only whitespace -> link-required", () => {
  assert.equal(
    requiredSourceError({ sourceType: "link", hasFile: false, link: "   " }),
    "link-required"
  );
});

test("requiredSourceError: link with a value -> null (passes)", () => {
  assert.equal(
    requiredSourceError({ sourceType: "link", hasFile: false, link: "https://example.com/task/1" }),
    null
  );
});

test("requiredSourceError: missing sourceType -> diagram-generation", () => {
  assert.equal(
    requiredSourceError({ sourceType: undefined, hasFile: false, link: "" }),
    "diagram-generation"
  );
});

test("requiredSourceError: unknown sourceType -> diagram-generation", () => {
  assert.equal(
    requiredSourceError({ sourceType: "totally-bogus", hasFile: true, link: "https://x" }),
    "diagram-generation"
  );
});

test("requiredSourceError: empty-string sourceType -> diagram-generation", () => {
  assert.equal(
    requiredSourceError({ sourceType: "", hasFile: false, link: "" }),
    "diagram-generation"
  );
});
