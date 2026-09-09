import assert from "node:assert/strict";
import test from "node:test";

import { createId } from "../../src/utils/id.ts";

test("createId uses randomUUID when the browser exposes it", () => {
  assert.equal(createId({ randomUUID: () => "native-id" }), "native-id");
});

test("createId creates a UUID with getRandomValues when randomUUID is unavailable", () => {
  const id = createId({
    getRandomValues: (bytes) => {
      bytes.forEach((_, index) => { bytes[index] = index; });
      return bytes;
    },
  });

  assert.equal(id, "00010203-0405-4607-8809-0a0b0c0d0e0f");
});

test("createId has a final fallback when Web Crypto is unavailable", () => {
  assert.match(createId({}), /^fallback-[a-z0-9]+-[a-z0-9]+$/);
});
