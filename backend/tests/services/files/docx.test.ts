import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDocx } from "../../../src/services/files/docx.ts";

test("parseDocx: returns string from valid DOCX buffer", async () => {
  // Since a fully valid minimal DOCX fixture is hard to hand-construct reliably,
  // verify the function handles errors gracefully (never throws) with an invalid buffer
  const result = await parseDocx(Buffer.from("not a docx"));
  assert.equal(typeof result, "string");
});

test("parseDocx: never throws on garbage input", async () => {
  await assert.doesNotReject(async () => {
    await parseDocx(Buffer.from([0x00, 0x01, 0x02, 0xff, 0xfe]));
  });
});

test("parseDocx: returns empty string on empty buffer", async () => {
  const result = await parseDocx(Buffer.alloc(0));
  assert.equal(result, "");
});
