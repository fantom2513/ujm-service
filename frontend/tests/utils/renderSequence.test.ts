import assert from "node:assert/strict";
import test from "node:test";

import { RenderSequence } from "../../src/utils/renderSequence.ts";

test("RenderSequence rejects an older render after a newer one starts", () => {
  const sequence = new RenderSequence();
  const first = sequence.start();
  const second = sequence.start();

  assert.equal(sequence.isCurrent(first), false);
  assert.equal(sequence.isCurrent(second), true);
});
