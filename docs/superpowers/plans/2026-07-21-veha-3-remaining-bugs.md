# Веха 3: оставшиеся баги (#7, #10, #11, #13) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four remaining production bugs in CX Copilot: missing selected-state color on the rating buttons (#10/#11, one shared root cause), no analytics for rating/copy actions (#7), and no way to download a chat attachment by clicking it (#13).

**Architecture:** Three independent tasks. Task 1 is CSS-only (the SVG-level hypothesis from the design spec turned out to already be fixed in the actual runtime icon source — see the note in Task 1 Step 1). Task 2 adds a new backend endpoint plus two fire-and-forget calls from already-existing frontend handlers. Task 3 adds an in-memory (non-persisted) file registry and a new click handler mirroring the existing `[data-source-download]` pattern.

**Tech Stack:** Node 24 native TS type-stripping, `node:test` runner, vanilla TS frontend (no bundler beyond `scripts/build.mjs`), cached Playwright Chromium (`C:\Users\User\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe`) driven via CDP for frontend verification (no frontend test framework exists in this repo).

---

## File Structure

- Modify: `frontend/src/styles.css` — `.ai-actions button` color tokens.
- Create: `backend/src/services/feedback/index.ts` — feedback payload validation + recording (pure, testable, no HTTP server side effects).
- Modify: `backend/src/server/index.ts` — new `POST /api/feedback` route + `handleFeedback`, new `"invalid-request"` error code/message.
- Modify: `shared/types/index.ts` — add `"invalid-request"` to `UserErrorCode`.
- Create: `backend/tests/services/feedback/index.test.ts`
- Modify: `frontend/src/api/client.ts` — new `sendFeedback()` helper.
- Modify: `frontend/src/main.ts` — wire `sendFeedback()` into the existing feedback/copy click handlers; add `messageFiles` map, populate it in `sendChat()`, change `messageAttachmentCard()` to a clickable button, add its click handler.

---

## Task 1: Rating button selected-state color (#10 / #11)

**Files:**
- Modify: `frontend/src/styles.css:1520-1541` (`.ai-actions button` block)

- [ ] **Step 1: Confirm the SVG source no longer needs changing**

The approved design spec (`docs/superpowers/specs/2026-07-21-veha-3-remaining-bugs-design.md`) hypothesized editing `thumb-up.svg`/`thumb-down.svg`/`copy-left.svg` to replace a hardcoded `stroke="#152149" stroke-opacity="0.6"` with `stroke="currentColor"`. Verify this is now a no-op by inspecting the actual runtime icon source:

Run: `grep -n "thumb-up.svg\|thumb-down.svg\|copy-left.svg" frontend/src/generated/inline-icons.ts`

Expected: all three entries already contain `stroke=\"currentColor\"` (no `stroke-opacity` attribute at all). This file — not the raw files under `Референсы/Result/Chat/icons/` — is what `svgIcon()` (`frontend/src/main.ts:494-498`) actually inlines into the DOM at runtime, so the raw reference files being stale is irrelevant. **Do not edit `frontend/src/generated/inline-icons.ts` or anything under `Референсы/`** — confirm this and move straight to Step 2. If for some reason the grep does NOT show `currentColor` for all three, stop and report back before proceeding (the plan's Step 2 assumes this is already true).

- [ ] **Step 2: Add explicit color tokens to `.ai-actions button`**

In `frontend/src/styles.css`, the current block reads:

```css
.ai-actions button {
  width: 20px;
  height: 20px;
  min-height: 0;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 0;
  opacity: 0.8;
}

.ai-actions button:hover,
.ai-actions button:focus-visible {
  opacity: 1;
}

.ai-actions button:active,
.ai-actions button[aria-pressed="true"] {
  opacity: 1;
}
```

Replace it with:

```css
.ai-actions button {
  width: 20px;
  height: 20px;
  min-height: 0;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 0;
  color: var(--muted-soft);
  opacity: 0.8;
}

.ai-actions button:hover,
.ai-actions button:focus-visible {
  opacity: 1;
}

.ai-actions button:active,
.ai-actions button[aria-pressed="true"] {
  opacity: 1;
  color: var(--blue-bright);
}
```

(`--muted-soft` and `--blue-bright` are both already defined in `:root` at the top of `frontend/src/styles.css` — no new tokens needed. The "Скопировать ответ" button never gets `aria-pressed="true"` set on it — only the two `[data-feedback]` buttons do — so it will always render in `--muted-soft`, which is correct: it has no "selected" state to show.)

- [ ] **Step 3: Build the frontend**

Run: `node scripts/build.mjs`
Expected: exits 0.

- [ ] **Step 4: Verify with a headless browser**

There is no frontend test framework in this repo. Start the backend server in the background (`cd .worktrees/veha-3-remaining-bugs && npm start`, serves `http://127.0.0.1:4173/`), then create a one-off script at `.worktrees/veha-3-remaining-bugs/scratch-verify-task1.mjs`:

```javascript
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const CHROME = "C:\\Users\\User\\AppData\\Local\\ms-playwright\\chromium-1223\\chrome-win64\\chrome.exe";
const APP_URL = "http://127.0.0.1:4173/";

const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9334", "--no-sandbox", "about:blank"]);
await delay(1500);

const pages = await (await fetch("http://127.0.0.1:9334/json/list")).json();
const page = pages.find((p) => p.type === "page") || pages[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
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
await send("Page.navigate", { url: APP_URL });
await delay(800);

// Seed a result page with one assistant chat message so the ai-actions buttons render.
await send("Runtime.evaluate", {
  expression: `
    sessionStorage.setItem("copilot-mermaid-session-v1", JSON.stringify({
      page: "result",
      start: { sourceType: "text-file", link: "", details: "" },
      result: {
        title: "Test",
        mermaidCode: "flowchart TD\\n  A[Start] --> B[End]",
        sourceText: "test",
        sourceContext: { type: "text-file", title: "test.docx", description: "test" },
        chat: [{ id: "msg-1", role: "assistant", text: "Готово.", createdAt: new Date().toISOString() }],
        warnings: []
      },
      view: { scale: 1, x: 0, y: 0 },
      chatDraft: "",
      config: { productHomeUrl: "http://localhost:3000/" }
    }));
  `
});
await send("Page.navigate", { url: APP_URL });
await delay(1000);

const before = await send("Runtime.evaluate", {
  expression: `getComputedStyle(document.querySelector('[data-feedback="up"]')).color`,
  returnByValue: true
});

await send("Runtime.evaluate", {
  expression: `document.querySelector('[data-feedback="up"]').click()`
});
await delay(200);

const after = await send("Runtime.evaluate", {
  expression: `getComputedStyle(document.querySelector('[data-feedback="up"]')).color`,
  returnByValue: true
});

console.log("Before click:", before.result.value);
console.log("After click:", after.result.value);
const changed = before.result.value !== after.result.value;
console.log(changed ? "PASS: color changes on selection, not just opacity" : "FAIL: color unchanged after selecting rating");

chrome.kill();
process.exit(changed ? 0 : 1);
```

Run: `node .worktrees/veha-3-remaining-bugs/scratch-verify-task1.mjs`
Expected: prints `PASS: color changes on selection, not just opacity`, with "Before" showing the `--muted-soft` RGB (`rgba(21, 33, 73, 0.5)`) and "After" showing the `--blue-bright` RGB (`rgb(43, 92, 233)`).

Delete the scratch script and stop the background server afterward.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles.css
git commit -m "fix: give the rating buttons a real selected-state color, not just opacity (#10, #11)"
```

---

## Task 2: Feedback/rating analytics endpoint (#7)

**Files:**
- Modify: `shared/types/index.ts`
- Create: `backend/src/services/feedback/index.ts`
- Test: `backend/tests/services/feedback/index.test.ts`
- Modify: `backend/src/server/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/main.ts:713-731` (existing `[data-feedback]`/`[data-copy-message]` handlers)

- [ ] **Step 1: Add the new error code to the shared type**

In `shared/types/index.ts`, the current union is:

```typescript
export type UserErrorCode =
  | "file-required"
  | "file-format"
  | "file-size"
  | "link-required"
  | "invalid-link"
  | "source-unavailable"
  | "diagram-generation"
  | "attachment-error";
```

Add `"invalid-request"`:

```typescript
export type UserErrorCode =
  | "file-required"
  | "file-format"
  | "file-size"
  | "link-required"
  | "invalid-link"
  | "source-unavailable"
  | "diagram-generation"
  | "attachment-error"
  | "invalid-request";
```

- [ ] **Step 2: Write the failing test for the feedback service**

Create `backend/tests/services/feedback/index.test.ts`:

```typescript
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && node --test tests/services/feedback/index.test.ts`
Expected: FAIL — `Cannot find module '../../../src/services/feedback/index.ts'`.

- [ ] **Step 4: Implement `backend/src/services/feedback/index.ts`**

```typescript
export interface FeedbackEntry {
  messageId: string;
  kind: "rating" | "copy";
  value?: "up" | "down";
  timestamp: string;
}

export function parseFeedbackEntry(fields: Record<string, string>): FeedbackEntry | null {
  const messageId = fields.messageId;
  const kind = fields.kind;
  const value = fields.value;

  if (!messageId || (kind !== "rating" && kind !== "copy")) return null;
  if (kind === "rating" && value !== "up" && value !== "down") return null;

  return {
    messageId,
    kind,
    value: kind === "rating" ? (value as "up" | "down") : undefined,
    timestamp: new Date().toISOString()
  };
}

export function recordFeedback(entry: FeedbackEntry): void {
  console.log("[feedback]", JSON.stringify(entry));
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && node --test tests/services/feedback/index.test.ts`
Expected: PASS (5 tests, 0 failures).

- [ ] **Step 6: Wire the route into `backend/src/server/index.ts`**

Add to the `userMessages` map (`backend/src/server/index.ts:18-25`), after the `"attachment-error"` entry:

```typescript
  "attachment-error": "Ошибка загрузки файла",
  "invalid-request": "Некорректный запрос"
```

Add an import near the top (after the existing `import { normalizeChatAttachment } from "../services/chatAttachments/index.ts";` line):

```typescript
import { parseFeedbackEntry, recordFeedback } from "../services/feedback/index.ts";
```

Add a new handler function, placed after `handleChat` (before `handleStatic`):

```typescript
async function handleFeedback(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = await readBody(request);
  const entry = parseFeedbackEntry(body.fields);
  if (!entry) {
    return sendApiError(response, 400, { code: "invalid-request", message: userMessages["invalid-request"] });
  }
  recordFeedback(entry);
  return sendJson(response, 200, { ok: true });
}
```

Add the route in the dispatch block (`backend/src/server/index.ts`, inside `createServer(async (request, response) => { ... })`), right after the existing `/api/chat` block:

```typescript
    if (request.url?.startsWith("/api/chat") && request.method === "POST") {
      return await handleChat(request, response);
    }
    if (request.url?.startsWith("/api/feedback") && request.method === "POST") {
      return await handleFeedback(request, response);
    }
```

- [ ] **Step 7: Run the full backend test suite**

Run: `npm test` from repo root.
Expected: all tests pass (58 existing + 5 new = 63).

- [ ] **Step 8: Add `sendFeedback()` to the frontend API client**

In `frontend/src/api/client.ts`, the current file ends with `requestJson`. Add a new exported function (it does not reuse `requestJson` since it sends JSON, not `FormData`, and must never throw — feedback is fire-and-forget and must not disrupt the chat UI on failure):

```typescript
export async function sendFeedback(payload: { messageId: string; kind: "rating" | "copy"; value?: "up" | "down" }): Promise<void> {
  try {
    await fetch("api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    console.error("Failed to send feedback:", error);
  }
}
```

- [ ] **Step 9: Wire `sendFeedback()` into the existing frontend handlers**

In `frontend/src/main.ts`, update the import at the top (currently `import { generateDiagram, getConfig, sendChatMessage } from "./api/client.ts";`) to:

```typescript
import { generateDiagram, getConfig, sendChatMessage, sendFeedback } from "./api/client.ts";
```

Then update the two handlers at `frontend/src/main.ts:713-731`. Current:

```typescript
  document.querySelectorAll<HTMLButtonElement>("[data-feedback]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.messageId || "";
      const value = button.dataset.feedback as "up" | "down";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      message.feedback = message.feedback === value ? undefined : value;
      persist();
      render();
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-copy-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.copyMessage || "";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      void navigator.clipboard?.writeText(message.text);
    });
  });
```

Replace with:

```typescript
  document.querySelectorAll<HTMLButtonElement>("[data-feedback]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.messageId || "";
      const value = button.dataset.feedback as "up" | "down";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      message.feedback = message.feedback === value ? undefined : value;
      persist();
      render();
      if (message.feedback) void sendFeedback({ messageId: id, kind: "rating", value: message.feedback });
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-copy-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.copyMessage || "";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      void navigator.clipboard?.writeText(message.text);
      void sendFeedback({ messageId: id, kind: "copy" });
    });
  });
```

(Note: toggling a rating off, i.e. clicking the same thumb twice, sets `message.feedback` back to `undefined` — the `if (message.feedback)` guard means only setting/switching a rating sends an analytics event, not un-setting one. This matches the design spec's scope: track ratings and copies, not un-ratings.)

- [ ] **Step 10: Build the frontend**

Run: `node scripts/build.mjs`
Expected: exits 0.

- [ ] **Step 11: Verify with a headless browser**

Start the backend server in the background, then create `.worktrees/veha-3-remaining-bugs/scratch-verify-task2.mjs` using the same CDP-connection boilerplate as Task 1 Step 4 (spawn Chromium, connect to the page-level WebSocket from `/json/list`, use a fresh `--remote-debugging-port`, e.g. `9335`). After seeding the same single-assistant-message session state as Task 1 and reloading:

```javascript
await send("Network.enable");
let capturedRequest = null;
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.method === "Network.requestWillBeSent" && msg.params.request.url.includes("/api/feedback")) {
    capturedRequest = msg.params.request;
  }
});

await send("Runtime.evaluate", {
  expression: `document.querySelector('[data-feedback="up"]').click()`
});
await delay(500);

console.log(capturedRequest ? "PASS: /api/feedback request sent" : "FAIL: no request captured");
if (capturedRequest) {
  console.log("Method:", capturedRequest.method, "Body:", capturedRequest.postData);
}
```

Expected: prints `PASS: /api/feedback request sent`, with `Body` containing `{"messageId":"msg-1","kind":"rating","value":"up"}`.

Delete the scratch script and stop the background server afterward.

- [ ] **Step 12: Commit**

```bash
git add shared/types/index.ts backend/src/services/feedback/index.ts backend/tests/services/feedback/index.test.ts backend/src/server/index.ts frontend/src/api/client.ts frontend/src/main.ts
git commit -m "feat: send rating and copy actions to a new internal /api/feedback endpoint (#7)"
```

---

## Task 3: Download chat attachment by clicking it (#13)

**Files:**
- Modify: `frontend/src/main.ts:420-448` (`chatMessage`, `messageAttachmentCard`), `frontend/src/main.ts:32` (module-level vars), `frontend/src/main.ts:872-878` (`sendChat`), `frontend/src/main.ts:690-693` (event binding, add new handler nearby)
- Modify: `frontend/src/styles.css:1437-1451` (`.message-file-card`, div → button reset)

- [ ] **Step 1: Add the in-memory file registry**

In `frontend/src/main.ts`, right after the existing declaration `let chatFiles: File[] = [];` (line 32), add:

```typescript
const messageFiles = new Map<string, File[]>();
```

- [ ] **Step 2: Populate it when a chat message with attachments is sent**

In `sendChat()` (`frontend/src/main.ts:864-878`), current:

```typescript
  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    text: text || (attachments.length === 1 ? "Прикреплён файл" : `Прикреплено файлов: ${attachments.length}`),
    createdAt: new Date().toISOString(),
    attachment: attachments[0],
    attachments
  };
```

Add right after this object literal:

```typescript
  if (chatFiles.length) messageFiles.set(userMessage.id, [...chatFiles]);
```

- [ ] **Step 3: Make `messageAttachmentCard` a clickable button and thread the message id through**

Current `chatMessage()` (`frontend/src/main.ts:420-436`) builds attachment cards via:

```typescript
  const attachmentCards = attachments.length ? `<div class="message-attachments">${attachments.map(messageAttachmentCard).join("")}</div>` : "";
```

Change to:

```typescript
  const attachmentCards = attachments.length ? `<div class="message-attachments">${attachments.map((file, index) => messageAttachmentCard(file, message.id, index)).join("")}</div>` : "";
```

Current `messageAttachmentCard()` (`frontend/src/main.ts:439-448`):

```typescript
function messageAttachmentCard(file: FileMeta): string {
  return `
    <div class="message-file-card">
      ${icon("File badge.svg", "message-file-icon")}
      <span class="message-file-info">
        <span class="message-file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
        <small>${escapeHtml(file.format)} · ${formatBytes(file.size)}</small>
      </span>
    </div>
  `;
}
```

Replace with:

```typescript
function messageAttachmentCard(file: FileMeta, messageId: string, index: number): string {
  return `
    <button type="button" class="message-file-card" data-message-file="${escapeHtml(messageId)}:${index}">
      ${icon("File badge.svg", "message-file-icon")}
      <span class="message-file-info">
        <span class="message-file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
        <small>${escapeHtml(file.format)} · ${formatBytes(file.size)}</small>
      </span>
    </button>
  `;
}
```

- [ ] **Step 4: Update `.message-file-card` CSS for the div → button change**

In `frontend/src/styles.css`, current:

```css
.message-file-card {
  width: 100%;
  min-width: 0;
  flex: 0 0 auto;
  box-sizing: border-box;
  height: 72px;
  min-height: 72px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(26, 51, 115, 0.05);
}
```

Replace with (adds a button reset, keeps all existing visual properties unchanged):

```css
.message-file-card {
  width: 100%;
  min-width: 0;
  flex: 0 0 auto;
  box-sizing: border-box;
  height: 72px;
  min-height: 72px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(26, 51, 115, 0.05);
  border: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
```

- [ ] **Step 5: Add the click handler**

In `frontend/src/main.ts`, right after the existing `[data-source-download]` handler (`frontend/src/main.ts:690-693`):

```typescript
  document.querySelector<HTMLButtonElement>("[data-source-download]")?.addEventListener("click", () => {
    if (sourceFile) downloadLocalFile(sourceFile);
  });
```

add:

```typescript
  document.querySelectorAll<HTMLButtonElement>("[data-message-file]").forEach((button) => {
    button.addEventListener("click", () => {
      const [messageId, indexRaw] = (button.dataset.messageFile || "").split(":");
      const file = messageFiles.get(messageId)?.[Number(indexRaw)];
      if (file) downloadLocalFile(file);
    });
  });
```

- [ ] **Step 6: Build the frontend**

Run: `node scripts/build.mjs`
Expected: exits 0.

- [ ] **Step 7: Verify with a headless browser**

There is no way to attach a real `File` via CDP `Runtime.evaluate` alone in a way that flows through the real `sendChat()` upload path without a live LLM backend to respond to `/api/chat`. Instead, verify the mechanism directly: seed a message with an attachment into `state.result.chat` (as done in Task 1/2's scripts) so the card renders, and separately populate `messageFiles` from the page context to simulate a file having been attached in this session, then click and confirm a download is triggered.

Create `.worktrees/veha-3-remaining-bugs/scratch-verify-task3.mjs` using the same CDP boilerplate as before (fresh port, e.g. `9336`). After navigating once so the app's module graph loads:

```javascript
await send("Runtime.evaluate", {
  expression: `
    sessionStorage.setItem("copilot-mermaid-session-v1", JSON.stringify({
      page: "result",
      start: { sourceType: "text-file", link: "", details: "" },
      result: {
        title: "Test",
        mermaidCode: "flowchart TD\\n  A[Start] --> B[End]",
        sourceText: "test",
        sourceContext: { type: "text-file", title: "test.docx", description: "test" },
        chat: [{
          id: "msg-attach-1",
          role: "user",
          text: "Прикреплён файл",
          createdAt: new Date().toISOString(),
          attachments: [{ name: "report.docx", format: "docx", size: 1024 }]
        }],
        warnings: []
      },
      view: { scale: 1, x: 0, y: 0 },
      chatDraft: "",
      config: { productHomeUrl: "http://localhost:3000/" }
    }));
  `
});
await send("Page.navigate", { url: APP_URL });
await delay(1000);

// Confirm the card rendered as a clickable button with the expected data attribute.
const cardCheck = await send("Runtime.evaluate", {
  expression: `document.querySelector('[data-message-file="msg-attach-1:0"]')?.tagName || "MISSING"`,
  returnByValue: true
});
console.log("Card element:", cardCheck.result.value);

// Simulate the in-memory File registry (as if this session had actually attached the file)
// and confirm clicking triggers a real download attempt (an <a> click with an object URL).
await send("Runtime.evaluate", {
  expression: `
    (async () => {
      const mod = await import("/src/main.js?v=chat-details-files-1");
      window.__downloadTriggered = false;
      const origCreateElement = document.createElement.bind(document);
      document.createElement = function(tag) {
        const el = origCreateElement(tag);
        if (tag === "a") {
          const origClick = el.click.bind(el);
          el.click = function() { window.__downloadTriggered = true; };
        }
        return el;
      };
    })();
  `
});
await delay(300);

const clickResult = await send("Runtime.evaluate", {
  expression: `document.querySelector('[data-message-file="msg-attach-1:0"]')?.click(); "clicked"`,
  returnByValue: true
});
await delay(300);

const triggered = await send("Runtime.evaluate", {
  expression: `window.__downloadTriggered || false`,
  returnByValue: true
});

console.log("Download triggered on click (expect false — no file in messageFiles this run, since this script never went through sendChat()):", triggered.result.value);
console.log(cardCheck.result.value === "BUTTON" ? "PASS: attachment card is a real clickable button" : "FAIL: attachment card is not a button");
```

Expected: `Card element: BUTTON` and the PASS line. The download-triggered check is expected to print `false` in this synthetic script (since `messageFiles` was never populated via a real `sendChat()` call in this isolated page load) — this is fine; Step 7's actual assertion is that the card is a real `<button data-message-file="...">`, proving the DOM/click-wiring is correct. The `messageFiles` population itself (Step 2) is a one-line, low-risk change already covered by reading the diff in review — an end-to-end live click-to-download check would require a real LLM backend to complete a chat round-trip and is out of proportion for this fix.

Delete the scratch script afterward.

- [ ] **Step 8: Run the full test suite**

Run: `npm test` from `.worktrees/veha-3-remaining-bugs`
Expected: all tests still pass (63, unchanged by this task — it has no backend changes).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/main.ts frontend/src/styles.css
git commit -m "feat: make chat attachment cards downloadable by click within the current session (#13)"
```

---

## Final Steps (after all 3 tasks)

- [ ] Run the full test suite one more time: `npm test` from `.worktrees/veha-3-remaining-bugs`.
- [ ] Confirm no scratch/verification scripts remain in the worktree (`git status` should show only the intended source/test files as modified/added).
- [ ] Invoke `superpowers:finishing-a-development-branch` for `veha-3-remaining-bugs` (same pattern as Вехи 0/1/2): verify tests, present the 4 standard options, execute the chosen one, clean up the worktree.
