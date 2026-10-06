import { pathToFileURL } from "node:url";
import { text } from "node:stream/consumers";

// Mermaid sanitizes labels while parsing; DOMPurify needs a DOM even without rendering.
const jsdomUrl = process.env.MERMAID_JSDOM_MODULE_PATH
  ? pathToFileURL(process.env.MERMAID_JSDOM_MODULE_PATH).href
  : "jsdom";
const { JSDOM } = await import(jsdomUrl);
const dom = new JSDOM("");
globalThis.window = dom.window;
globalThis.document = dom.window.document;

const moduleUrl = process.env.MERMAID_MODULE_PATH
  ? pathToFileURL(process.env.MERMAID_MODULE_PATH).href
  : new URL("../../../node_modules/mermaid/dist/mermaid.esm.min.mjs", import.meta.url).href;
const { default: mermaid } = await import(moduleUrl);
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", suppressErrorRendering: true });

try {
  const code = await text(process.stdin);
  const ok = await mermaid.parse(code);
  process.stdout.write(JSON.stringify(ok ? { ok: true } : { ok: false, reason: "Mermaid parse failed" }));
} catch (error) {
  if (error instanceof TypeError || error instanceof ReferenceError) {
    process.stderr.write(String(error.message));
    process.exitCode = 1;
  } else {
    process.stdout.write(JSON.stringify({
      ok: false,
      reason: String(error instanceof Error ? error.message : error).slice(0, 1000),
    }));
  }
} finally {
  dom.window.close();
}
