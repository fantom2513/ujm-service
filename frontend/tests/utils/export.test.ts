import assert from "node:assert/strict";
import test from "node:test";

import { renderMermaid } from "../../src/utils/export.ts";

test("renderMermaid shows a rendering error instead of an endless loading placeholder", async () => {
  const originalConsoleError = console.error;
  console.error = () => undefined;
  try {
    const svg = await renderMermaid("not valid Mermaid");

    assert.match(svg, /Не удалось отобразить схему/);
    assert.doesNotMatch(svg, /Схема загружается/);
  } finally {
    console.error = originalConsoleError;
  }
});
