import { test } from "node:test";
import assert from "node:assert/strict";
import { validateMermaid } from "../../../src/services/mermaid/index.ts";

test("validateMermaid: accepts flowchart LR", () => {
  assert.equal(validateMermaid("flowchart LR\nA-->B").ok, true);
});

test("validateMermaid: accepts flowchart TB (model uses TB for complex diagrams)", () => {
  assert.equal(validateMermaid("flowchart TB\nA-->B").ok, true);
});

test("validateMermaid: accepts TD/BT/RL directions", () => {
  for (const dir of ["TD", "BT", "RL"]) {
    assert.equal(validateMermaid(`flowchart ${dir}\nA-->B`).ok, true, `direction ${dir}`);
  }
});

test("validateMermaid: rejects non-flowchart", () => {
  assert.equal(validateMermaid("graph LR\nA-->B").ok, false);
});

test("validateMermaid: rejects XSS content", () => {
  const result = validateMermaid('flowchart LR\nA-->B["<script>alert(1)</script>"]');
  assert.equal(result.ok, false);
});
