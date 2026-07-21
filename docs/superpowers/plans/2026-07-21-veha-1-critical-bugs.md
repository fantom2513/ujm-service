# Веха 1: критичные прод-баги (#1, #2/mojibake, #8, #12) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four critical production bugs in CX Copilot without touching code outside their scope: schema not reloading after navigation/refresh (#1), mojibake in uploaded filenames (#2), broken PNG export (#8), and silent diagram generation without an attached file (#12).

**Architecture:** Four independent, self-contained tasks. Task 1 extracts the pure `parseMultipart` function out of the side-effecting HTTP server entrypoint into its own testable module and fixes the filename decoding bug. Task 2 adds a missing re-render call on frontend state restore. Tasks 3 and 4 start with reproduction/investigation (root cause not fully confirmed in the design spec) before landing a fix — same pattern used for bugs #14/#17 in Веха 2.

**Tech Stack:** Node 24 native TS type-stripping, `node:test` runner, vanilla TS frontend (no bundler beyond `scripts/build.mjs`), Mermaid 11 (loaded from CDN at runtime), cached Playwright Chromium (`C:\Users\User\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe`) driven directly via Chrome DevTools Protocol (CDP) with Node's native `fetch`/`WebSocket` for frontend verification (no test framework exists for the frontend).

---

## File Structure

- Create: `backend/src/server/multipart.ts` — pure multipart/form-data parser, extracted from `backend/src/server/index.ts` (currently defined inline in a file that also starts a real HTTP listener at module load, which makes it unsafe to `import` from a test file).
- Create: `backend/tests/server/multipart.test.ts` — unit tests for the extracted parser, including the filename-encoding fix.
- Modify: `backend/src/server/index.ts` — remove the inline `parseMultipart` definition, import it from `./multipart.ts` instead.
- Modify: `frontend/src/main.ts` — add a `restoreResultView()` helper and call it on initial load and on `popstate`.
- Modify: `frontend/src/utils/export.ts` (Task 3, pending investigation outcome) — PNG export fix.
- Modify: `backend/src/server/index.ts` and/or `frontend/src/main.ts` (Task 4, pending investigation outcome) — silent-generation-without-file fix.

---

## Task 1: Extract `parseMultipart` and fix filename encoding (#2 / mojibake)

**Files:**
- Create: `backend/src/server/multipart.ts`
- Modify: `backend/src/server/index.ts:1-13` (imports), `backend/src/server/index.ts:60-96` (remove inline function)
- Test: `backend/tests/server/multipart.test.ts`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/server/multipart.test.ts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseMultipart } from "../../src/server/multipart.ts";

function buildMultipartBuffer(boundary: string, filename: string, fileContent: string, extraField?: { name: string; value: string }): Buffer {
  const parts: Buffer[] = [];
  if (extraField) {
    parts.push(Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="${extraField.name}"\r\n\r\n${extraField.value}\r\n`,
      "utf8"
    ));
  }
  parts.push(Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: text/plain\r\n\r\n`,
    "utf8"
  ));
  parts.push(Buffer.from(fileContent, "utf8"));
  parts.push(Buffer.from(`\r\n--${boundary}--\r\n`, "utf8"));
  return Buffer.concat(parts);
}

test("parseMultipart: decodes a Cyrillic filename correctly", () => {
  const boundary = "testboundary123";
  const cyrillicFilename = "Утвержденное ТЗ.docx";
  const buffer = buildMultipartBuffer(boundary, cyrillicFilename, "hello world");
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.files.length, 1);
  assert.equal(result.files[0].filename, cyrillicFilename);
});

test("parseMultipart: still decodes plain ASCII filenames correctly", () => {
  const boundary = "testboundary456";
  const buffer = buildMultipartBuffer(boundary, "report.docx", "hello world");
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.files[0].filename, "report.docx");
});

test("parseMultipart: still decodes UTF-8 field values correctly (regression guard)", () => {
  const boundary = "testboundary789";
  const buffer = buildMultipartBuffer(boundary, "report.docx", "hello world", { name: "details", value: "Проверка полей" });
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.fields.details, "Проверка полей");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && node --test tests/server/multipart.test.ts`
Expected: FAIL — `Cannot find module '../../src/server/multipart.ts'` (module doesn't exist yet).

- [ ] **Step 3: Create `backend/src/server/multipart.ts` with the extracted and fixed parser**

```typescript
import type { MultipartBody, UploadedFile } from "../types/index.ts";

export function parseMultipart(buffer: Buffer, contentType: string): MultipartBody {
  const boundaryMatch = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType);
  if (!boundaryMatch) return { fields: {}, files: [] };
  const boundary = boundaryMatch[1] || boundaryMatch[2];
  const raw = buffer.toString("latin1");
  const parts = raw.split(`--${boundary}`).slice(1, -1);
  const fields: Record<string, string> = {};
  const files: UploadedFile[] = [];

  for (const part of parts) {
    const normalizedPart = part.replace(/^\r\n/, "").replace(/\r\n$/, "");
    const headerEnd = normalizedPart.indexOf("\r\n\r\n");
    if (headerEnd === -1) continue;

    const headerText = normalizedPart.slice(0, headerEnd);
    const bodyText = normalizedPart.slice(headerEnd + 4);
    const disposition = /content-disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="([^"]*)")?/i.exec(headerText);
    if (!disposition) continue;

    const fieldName = disposition[1];
    const filename = disposition[2] ? Buffer.from(disposition[2], "latin1").toString("utf8") : undefined;
    const typeMatch = /content-type:\s*([^\r\n]+)/i.exec(headerText);
    const contentTypeHeader = typeMatch?.[1]?.trim() || "application/octet-stream";

    if (filename) {
      const bodyBuffer = Buffer.from(bodyText, "latin1");
      files.push({
        fieldName,
        filename,
        contentType: contentTypeHeader,
        size: bodyBuffer.length,
        buffer: bodyBuffer
      });
    } else {
      fields[fieldName] = Buffer.from(bodyText, "latin1").toString("utf8");
    }
  }

  return { fields, files };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && node --test tests/server/multipart.test.ts`
Expected: PASS (3 tests, 0 failures).

- [ ] **Step 5: Wire `backend/src/server/index.ts` to use the extracted module**

In `backend/src/server/index.ts`, add to the top imports (after the existing `import { config } from "../config/index.ts";` line):

```typescript
import { parseMultipart } from "./multipart.ts";
```

Then delete the entire inline `function parseMultipart(...) { ... }` block (currently spanning from `function parseMultipart(buffer: Buffer, contentType: string): MultipartBody {` down to its closing `}`, right before `async function readBody`). Also remove the now-unused `UploadedFile` import from `../types/index.ts` in this file if `MultipartBody`/`UploadedFile` are still needed elsewhere in the file, keep only the ones still referenced (check `firstFile`, `handleGenerate`, `handleChat` — `UploadedFile` and `MultipartBody` are both still used as types elsewhere in `index.ts`, so keep both imports; only the function body moves out).

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && node --test` (or `npm test` from repo root)
Expected: all tests pass, including the 3 new multipart tests (58/58 total, up from 55).

- [ ] **Step 7: Commit**

```bash
git add backend/src/server/multipart.ts backend/src/server/index.ts backend/tests/server/multipart.test.ts
git commit -m "fix: decode multipart filename as UTF-8 to fix mojibake (#2)"
```

---

## Task 2: Restore diagram render on page load / navigation (#1)

**Files:**
- Modify: `frontend/src/main.ts:812-820` (after `renderMermaidAndUpdate`), `frontend/src/main.ts:1200-1204` (popstate handler + bottom-of-file init call)

- [ ] **Step 1: Add a `restoreResultView()` helper right after `renderMermaidAndUpdate`**

In `frontend/src/main.ts`, immediately after the existing function:

```typescript
async function renderMermaidAndUpdate(code: string): Promise<void> {
  await renderMermaid(code);
  const content = document.querySelector<HTMLDivElement>("#diagram-content");
  if (content) {
    content.innerHTML = getCachedSvg();
    state.view = centeredView();
    applyTransform(content);
    persist();
  }
}
```

add:

```typescript
function restoreResultView(): void {
  if (state.page === "result" && state.result) {
    void renderMermaidAndUpdate(state.result.mermaidCode);
  }
}
```

- [ ] **Step 2: Call it from the `popstate` handler and from initial load**

Replace the tail of `frontend/src/main.ts` (currently):

```typescript
window.addEventListener("popstate", () => {
  state = loadState();
  render();
});

render();
```

with:

```typescript
window.addEventListener("popstate", () => {
  state = loadState();
  render();
  restoreResultView();
});

render();
restoreResultView();
```

- [ ] **Step 3: Build the frontend**

Run: `node scripts/build.mjs`
Expected: exits 0, `frontend/dist` updated.

- [ ] **Step 4: Verify with a headless browser (no frontend test framework exists in this repo — manual/CDP verification only)**

Start the backend server in the background:

Run: `cd C:/work/ujm-service/.worktrees/veha-1-critical-bugs && npm start` (run in background — this serves `frontend/dist` and listens on `127.0.0.1:4173` per `backend/src/config/index.ts` defaults)

Create a one-off verification script at `.worktrees/veha-1-critical-bugs/scratch-verify-task2.mjs`:

```javascript
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const CHROME = "C:\\Users\\User\\AppData\\Local\\ms-playwright\\chromium-1223\\chrome-win64\\chrome.exe";
const APP_URL = "http://127.0.0.1:4173/";

const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9333", "--no-sandbox", "about:blank"]);
await delay(1500);

const { webSocketDebuggerUrl } = await (await fetch("http://127.0.0.1:9333/json/version")).json();
const ws = new WebSocket(webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve));

let id = 0;
function send(method, params = {}) {
  return new Promise((resolve) => {
    const messageId = ++id;
    const handler = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id === messageId) {
        ws.removeEventListener("message", handler);
        resolve(msg.result);
      }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ id: messageId, method, params }));
  });
}

await send("Page.enable");
await send("Runtime.enable");

// Seed sessionStorage with a fake completed result, then load the app so it
// restores straight into the result page — this is the exact scenario from
// bug #1 (schema present in state, but the SVG never got (re-)rendered).
await send("Page.navigate", { url: APP_URL });
await delay(800);
await send("Runtime.evaluate", {
  expression: `
    sessionStorage.setItem("copilot-mermaid-session-v1", JSON.stringify({
      page: "result",
      start: { sourceType: "text-file", link: "", details: "" },
      result: {
        title: "Test diagram",
        mermaidCode: "flowchart TD\\n  A[Start] --> B[End]",
        sourceText: "test",
        sourceContext: { type: "text-file", title: "test.docx", description: "test" },
        chat: [],
        warnings: []
      },
      view: { scale: 1, x: 0, y: 0 },
      chatDraft: "",
      config: { productHomeUrl: "http://localhost:3000/" }
    }));
  `
});

// Reload — this is the "F5 on the result page" scenario from bug #1.
await send("Page.navigate", { url: APP_URL });
await delay(2500); // allow the CDN mermaid import + render to complete

const { result } = await send("Runtime.evaluate", {
  expression: `document.querySelector("#diagram-content")?.innerHTML || ""`,
  returnByValue: true
});

const html = result.value;
const hasRealSvg = html.includes("<svg") && !html.includes("Схема загружается");
console.log(hasRealSvg ? "PASS: real diagram rendered after reload" : "FAIL: placeholder still shown after reload");
console.log(html.slice(0, 200));

chrome.kill();
process.exit(hasRealSvg ? 0 : 1);
```

Run: `node .worktrees/veha-1-critical-bugs/scratch-verify-task2.mjs`
Expected: prints `PASS: real diagram rendered after reload`.

If it prints FAIL, inspect the logged HTML snippet — if it's still the empty `#diagram-content` placeholder, check that `restoreResultView()` was actually added at both call sites (Step 2) and that the build in Step 3 was re-run before starting the server.

Delete the scratch script and stop the background server once verified:

Run: `rm .worktrees/veha-1-critical-bugs/scratch-verify-task2.mjs`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.ts
git commit -m "fix: re-render diagram on page load and popstate to fix stuck loading placeholder (#1)"
```

---

## Task 3: Investigate and fix PNG export (#8)

**Files:**
- Modify: `frontend/src/utils/export.ts` (exact change depends on Step 1 findings)

- [ ] **Step 1: Reproduce with a real Mermaid diagram containing `foreignObject`**

Create a one-off script at `.worktrees/veha-1-critical-bugs/scratch-verify-task3.mjs` using the same CDP-driving pattern as Task 2 Step 4 (spawn the cached Chromium at `C:\Users\User\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe`, connect over the DevTools WebSocket). Instead of seeding a trivial `flowchart TD` diagram, seed one that matches what the `HIGHLIGHT_MAIN_PATH`/decision-node prompts actually produce (with `classDef decision fill:#ECECFF,...` applied to a node — see `backend/src/prompts/generateMermaid.prompt.txt` for the exact class names in use), so the rendered SVG is representative of production output. After the page loads and mermaid renders, use `Runtime.evaluate` to call the app's exported PNG download path directly:

```javascript
// Inside the Runtime.evaluate expression, after confirming #diagram-content has a real <svg>:
`
  import("/src/utils/export.ts").then(async (mod) => {
    try {
      await mod.downloadPng();
      window.__pngExportResult = "ok";
    } catch (err) {
      window.__pngExportResult = "error: " + err.message;
    }
  });
`
```

Wait ~1s, then read `window.__pngExportResult` via another `Runtime.evaluate`. Record the exact error message if one occurs (e.g. `SecurityError: Failed to execute 'toBlob' on 'HTMLCanvasElement': Tainted canvases may not be exported.` would confirm the `foreignObject`-tainted-canvas hypothesis from the design spec).

- [ ] **Step 2: Based on the confirmed error, apply the fix**

If Step 1 confirms a tainted-canvas `SecurityError` (the hypothesis in the design spec): the fix is to stop loading the SVG through a `blob:` object URL `<img>` (which taints the canvas once the SVG contains `foreignObject` HTML content) and instead inline the SVG as a `data:image/svg+xml;base64,...` URI, which does not taint the canvas in Chromium-based browsers for same-origin-equivalent data URIs. In `frontend/src/utils/export.ts`, change `downloadPng()`:

```typescript
export async function downloadPng(): Promise<void> {
  const svg = getCachedSvg();
  const dataUrl = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
  const image = await loadImage(dataUrl);
  const { width, height } = diagramSize();
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error("PNG export failed")), "image/png");
  });
  downloadBlob(blob, filename("png"));
}
```

(Note: this removes the `URL.createObjectURL`/`URL.revokeObjectURL`/`finally` block entirely, since there's no object URL to revoke anymore.)

If Step 1 reveals a *different* error (not a tainted-canvas `SecurityError` — e.g. a CORS error tied to the CDN-loaded `mermaid.esm.min.mjs` script itself, or something else entirely), stop and report the exact error text before writing a fix — the fix above only applies to the tainted-canvas case.

- [ ] **Step 3: Re-run the Step 1 reproduction script against the fixed code**

Run: `node scripts/build.mjs` then re-run `node .worktrees/veha-1-critical-bugs/scratch-verify-task3.mjs`
Expected: `window.__pngExportResult` is `"ok"`, and additionally assert the downloaded blob is non-trivial: in the same `Runtime.evaluate` call, capture the blob size before triggering the download (e.g. temporarily stash `blob.size` on `window.__pngBlobSize` inside `downloadPng` during this manual check, or simpler — call `canvas.toBlob` directly in the evaluated expression and read `.size`) and assert it's greater than 500 bytes (an empty/blank PNG at this diagram size would be implausibly small).

- [ ] **Step 4: Delete the scratch script**

Run: `rm .worktrees/veha-1-critical-bugs/scratch-verify-task3.mjs`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/export.ts
git commit -m "fix: use data URI instead of blob URL for PNG export to avoid tainted-canvas error (#8)"
```

(If Step 2 finds a different root cause than expected, adjust the commit message and diff accordingly — the important invariant is that Step 3's re-run passes before committing.)

---

## Task 4: Investigate and fix silent generation without a file (#12)

**Files:**
- Modify: `backend/src/server/index.ts` (most likely — `handleGenerate`, `backend/src/server/index.ts:121-160`) and/or `frontend/src/main.ts` (`buildDiagram`/`validateBeforeSubmit`, around `frontend/src/main.ts:807-850` and `951-962`), exact file(s) depend on Step 1 findings.

- [ ] **Step 1: Reproduce by calling `/api/generate` directly, bypassing the frontend**

The frontend's `validateBeforeSubmit()` (`frontend/src/main.ts:951-962`) blocks submission without a file for all three `sourceType` values, and `handleGenerate` (`backend/src/server/index.ts:121-160`) checks `!file || !file.filename` for `"text-file"` and `"recording"`. Confirm whether the backend validation actually holds by sending a raw HTTP request that skips the frontend entirely:

```bash
curl -X POST http://127.0.0.1:4173/api/generate \
  -F "sourceType=text-file" \
  -F "details=Test details with no file attached"
```

(Start the server first: `cd .worktrees/veha-1-critical-bugs && npm start`, run in background.)

Expected if backend validation is intact: HTTP 400 with `{"ok":false,"error":{"code":"file-required",...}}`.

If this returns a 400 as expected, the backend is safe and the bug must be a frontend-only path — proceed to Step 1b. If it does NOT return a 400 (e.g. it proceeds to call the LLM and returns 200 with a fabricated diagram), the backend validation has a gap — proceed to Step 1c.

- [ ] **Step 1b: If backend validation holds, look for a frontend race between `selectedFile` and form submission**

Check `frontend/src/main.ts` around `buildDiagram()` (`frontend/src/main.ts:807-850`): `state.start.error = validateBeforeSubmit()` runs synchronously and reads the module-level `selectedFile` variable, then a few lines later `if (selectedFile) form.set("file", selectedFile);` reads it again. Since both reads are synchronous with no `await` between them (nothing user-triggered can run in between), a race here is unlikely for the file-required path itself — but check whether any of the three quick-action buttons ("Разбить схему на смысловые блоки", "Упростить схему", "Выделить основной путь" — visible in the chat panel) or the "Новая схема"/regeneration flow can trigger a *second* generation call reusing stale `state.start` while `selectedFile` has already been cleared (e.g. via `clearSourceFile()` around `frontend/src/main.ts:521-524`) by an unrelated interaction. Search for all call sites of `buildDiagram(` to enumerate every trigger path:

Run: `grep -n "buildDiagram(" frontend/src/main.ts`

For each call site found, trace whether `selectedFile` could be `undefined` at that point while the UI still displays an attached file (state desync). Report the exact trigger path found.

- [ ] **Step 1c: If backend validation has a gap, identify exactly which condition is missing**

Compare the three `sourceType` branches in `handleGenerate` (`backend/src/server/index.ts:121-160` — `"text-file"`, `"recording"`, and the `"link"` branch that follows). If `curl` with `sourceType=link` and no `link` field also produces an uncaught path, or if a `sourceType` value outside the three expected ones (e.g. missing/empty `sourceType`) falls through to a default `source` construction without a `file-required`-style error, that's the gap. Report the exact missing branch/condition.

- [ ] **Step 2: Write a regression test for whichever gap was found in Step 1b or 1c**

If the gap is on the backend (Step 1c), add to a new test file `backend/tests/server/handleGenerate.test.ts` (create it) exercising the exact missing branch found — write the concrete test once the branch is known, following the existing pattern in `backend/tests/services/openai/prompts.test.ts` (import from `../../src/...`, `node:test` + `node:assert/strict`). This step cannot be pre-written without knowing Step 1's outcome; write it as soon as Step 1 completes, before touching any implementation code (TDD: red first).

If the gap is frontend-only (Step 1b), describe the exact race/desync condition found and reproduce it manually via the CDP scripting pattern from Task 2 Step 4: seed the specific UI state that triggers it, perform the action, and assert (via `Runtime.evaluate` reading `document.querySelector(...)`) that a diagram-generation network request fires without a file attached where the UI implies one is present. This is the "red" step for the frontend case since no frontend test framework exists.

- [ ] **Step 3: Fix the gap**

Backend gap: add the missing validation branch in `handleGenerate`, following the exact style of the existing `"text-file"`/`"recording"` checks (return `sendApiError(response, 400, { code: "file-required", message: userMessages["file-required"] })` at the point where the branch currently proceeds without a file).

Frontend gap: fix the specific desync found in Step 1b at its source (e.g. don't let `selectedFile` become stale relative to what the UI displays, or re-run `validateBeforeSubmit()` immediately before reading `selectedFile` into the `FormData` rather than only once at the top of `buildDiagram()`).

- [ ] **Step 4: Run the Step 2 test/reproduction again to confirm it now passes ("green")**

Backend: `cd backend && node --test tests/server/handleGenerate.test.ts` (or `npm test` for the full suite) — expect PASS.
Frontend: re-run the Step 2 CDP script — expect the assertion to now show the UI correctly blocking/erroring instead of silently generating.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `npm test` from `.worktrees/veha-1-critical-bugs`
Expected: all tests pass (baseline 58 after Task 1, plus whatever Task 3/4 added).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "fix: prevent silent diagram generation without an attached file (#12)"
```

(Adjust the `git add` paths to the actual files touched once Step 1's findings are known.)

---

## Final Steps (after all 4 tasks)

- [ ] Run the full test suite one more time: `npm test` from `.worktrees/veha-1-critical-bugs`.
- [ ] Confirm no scratch/verification scripts remain in the worktree (`git status` should show only the intended source/test files as modified/added).
- [ ] Invoke `superpowers:finishing-a-development-branch` for `veha-1-critical-bugs` (same pattern as Веха 0 and Веха 2): verify tests, present the 4 standard options, execute the chosen one, clean up the worktree.
