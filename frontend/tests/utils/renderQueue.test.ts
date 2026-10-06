import assert from "node:assert/strict";
import test from "node:test";

import { RenderQueue } from "../../src/utils/renderQueue.ts";

test("RenderQueue runs one asynchronous render at a time", async () => {
  const queue = new RenderQueue();
  const started: string[] = [];
  let finishFirst: (() => void) | undefined;

  const first = queue.run(async () => {
    started.push("first");
    await new Promise<void>((resolve) => { finishFirst = resolve; });
    return "first";
  });
  const second = queue.run(async () => {
    started.push("second");
    return "second";
  });

  await Promise.resolve();
  assert.deepEqual(started, ["first"]);

  finishFirst?.();
  assert.deepEqual(await Promise.all([first, second]), ["first", "second"]);
  assert.deepEqual(started, ["first", "second"]);
});
