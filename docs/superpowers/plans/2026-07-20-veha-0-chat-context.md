# Веха 0: контекст чата + usage-трекинг — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix chat losing conversation context (root cause of bug #15 "выдели основной путь" and likely #9) by threading a windowed message history from the frontend into the LLM edit prompt, and lay groundwork for future context-budget tracking by surfacing LLM token usage through the chat response.

**Architecture:** No server-side sessions/DB — the frontend already persists the full chat transcript in `sessionStorage` (`state.result.chat`). `sendChat` will slice the last N messages and send them alongside the existing per-request fields; `buildChatPrompt` gains a `<CHAT_HISTORY>` block. Separately, `VLLMClient` will capture the `usage` object OpenAI-compatible responses return, expose it via a `lastUsage` field, and `chatEdit` will read it off the client that actually succeeded (fallback chain may try multiple clients) and return it to the HTTP layer.

**Tech Stack:** Node 24 native TS (type-stripping, no bundler), `node:test` for backend tests, vanilla TS frontend (no test framework — verified manually).

---

## Reference: files touched

- `backend/src/services/openai/prompts.ts` — `ChatPromptOptions` + `buildChatPrompt`
- `backend/src/infrastructure/llm/client.ts` — `VLLMClient` usage capture
- `backend/src/services/openai/index.ts` — `chatEdit` usage capture + `ChatEditResult`
- `backend/src/server/index.ts` — `handleChat` history parsing + response shape
- `frontend/src/main.ts` — `sendChat` history window
- `backend/tests/services/openai/prompts.test.ts`
- `backend/tests/services/openai/chatEdit.test.ts`
- `backend/tests/infrastructure/llm/client.test.ts`

---

### Task 1: `buildChatPrompt` accepts and renders chat history

**Files:**
- Modify: `backend/src/services/openai/prompts.ts`
- Test: `backend/tests/services/openai/prompts.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/services/openai/prompts.test.ts` (after the existing `buildChatPrompt: contains all required fields` test):

```typescript
test("buildChatPrompt: includes chat history when provided", () => {
  const prompt = buildChatPrompt({
    sourceText: "ТЗ",
    additionalDetails: "детали",
    currentMermaid: "flowchart LR\nA-->B",
    previousMermaid: undefined,
    actionType: "FREEFORM",
    userMessage: "добавь экран",
    attachmentContext: "",
    history: [
      { role: "user", text: "покажи процесс оплаты" },
      { role: "assistant", text: "Добавил узел оплаты." },
    ],
  });
  assert.ok(prompt.includes("<CHAT_HISTORY>"));
  assert.ok(prompt.includes("покажи процесс оплаты"));
  assert.ok(prompt.includes("Добавил узел оплаты."));
});

test("buildChatPrompt: empty history renders empty tag", () => {
  const prompt = buildChatPrompt({
    sourceText: "ТЗ",
    additionalDetails: "детали",
    currentMermaid: "flowchart LR\nA-->B",
    previousMermaid: undefined,
    actionType: "FREEFORM",
    userMessage: "добавь экран",
    attachmentContext: "",
    history: [],
  });
  assert.ok(prompt.includes("<CHAT_HISTORY></CHAT_HISTORY>"));
});
```

Also update the existing test in the same file (`buildChatPrompt: contains all required fields`) to pass `history: []` in its options object — it will fail to type-check otherwise once `history` becomes required:

```typescript
test("buildChatPrompt: contains all required fields", () => {
  const prompt = buildChatPrompt({
    sourceText: "ТЗ",
    additionalDetails: "детали",
    currentMermaid: "flowchart LR\nA-->B",
    previousMermaid: undefined,
    actionType: "FREEFORM",
    userMessage: "добавь экран",
    attachmentContext: "",
    history: [],
  });
  assert.ok(prompt.includes("flowchart LR"));
  assert.ok(prompt.includes("добавь экран"));
  assert.ok(prompt.includes("FREEFORM"));
});
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `node --test backend/tests/services/openai/prompts.test.ts`
Expected: FAIL — `history` does not exist on type `ChatPromptOptions` (TS type error surfaces as a runtime/module error under type-stripping, or `buildChatPrompt` simply ignores the field and the "includes CHAT_HISTORY" assertions fail).

- [ ] **Step 3: Implement `history` support in `prompts.ts`**

In `backend/src/services/openai/prompts.ts`, add a `HistoryEntry` type, extend `ChatPromptOptions`, add a formatter, and insert the block into `buildChatPrompt`:

```typescript
export interface HistoryEntry {
  role: "user" | "assistant";
  text: string;
}

export interface ChatPromptOptions {
  sourceText: string;
  additionalDetails: string;
  currentMermaid: string;
  previousMermaid: string | undefined;
  actionType: "FREEFORM" | "GROUP_SEMANTIC_BLOCKS" | "SIMPLIFY" | "HIGHLIGHT_MAIN_PATH" | "RESTORE_PREVIOUS";
  userMessage: string;
  attachmentContext: string;
  history: HistoryEntry[];
}

function formatHistory(history: HistoryEntry[]): string {
  return history
    .map((entry) => `${entry.role === "user" ? "Пользователь" : "Ассистент"}: ${sanitize(entry.text)}`)
    .join("\n");
}
```

Modify `buildChatPrompt` to build and insert the block (place it right after `prevBlock`, before `<ACTION_TYPE>`):

```typescript
export function buildChatPrompt(opts: ChatPromptOptions): string {
  const prevBlock = opts.previousMermaid
    ? `<PREVIOUS_MERMAID>\n${opts.previousMermaid}\n</PREVIOUS_MERMAID>`
    : `<PREVIOUS_MERMAID></PREVIOUS_MERMAID>`;

  const historyBlock = opts.history.length
    ? `<CHAT_HISTORY>\n${formatHistory(opts.history)}\n</CHAT_HISTORY>`
    : `<CHAT_HISTORY></CHAT_HISTORY>`;

  const attachBlock = opts.attachmentContext
    ? `<ATTACHMENT_CONTEXT>\n${sanitize(opts.attachmentContext)}\n</ATTACHMENT_CONTEXT>`
    : `<ATTACHMENT_CONTEXT></ATTACHMENT_CONTEXT>`;

  return `${EDIT_SYSTEM}

<SOURCE_SPECIFICATION>
${sanitize(opts.sourceText)}
</SOURCE_SPECIFICATION>

<ADDITIONAL_DETAILS>
${sanitize(opts.additionalDetails)}
</ADDITIONAL_DETAILS>

<CURRENT_MERMAID>
${opts.currentMermaid}
</CURRENT_MERMAID>

${prevBlock}

${historyBlock}

<ACTION_TYPE>
${opts.actionType}
</ACTION_TYPE>

<USER_MESSAGE>
${sanitize(opts.userMessage)}
</USER_MESSAGE>

${attachBlock}`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test backend/tests/services/openai/prompts.test.ts`
Expected: PASS (all tests in the file, including the two new ones and the updated one)

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/openai/prompts.ts backend/tests/services/openai/prompts.test.ts
git commit -m "feat: add chat history block to edit prompt"
```

---

### Task 2: `chatEdit.test.ts` helper picks up the new required field

**Files:**
- Modify: `backend/tests/services/openai/chatEdit.test.ts`

- [ ] **Step 1: Update the `opts()` helper**

`chatEdit.test.ts` builds `ChatPromptOptions` via a local `opts()` helper. After Task 1, `history` is a required field, so this file will fail to type-check. Update the helper:

```typescript
function opts(overrides: Partial<ChatPromptOptions> = {}): ChatPromptOptions {
  return {
    sourceText: "some source",
    additionalDetails: "",
    currentMermaid: "flowchart LR\nA --> B",
    previousMermaid: undefined,
    actionType: "FREEFORM",
    userMessage: "add a node",
    attachmentContext: "",
    history: [],
    ...overrides
  };
}
```

- [ ] **Step 2: Run the full existing suite for this file to confirm nothing broke**

Run: `node --test backend/tests/services/openai/chatEdit.test.ts`
Expected: PASS (both pre-existing tests still pass with `history: []` default)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/openai/chatEdit.test.ts
git commit -m "test: default chatEdit test options to empty history"
```

---

### Task 3: Server passes parsed history through to `chatEdit`

**Files:**
- Modify: `backend/src/server/index.ts`

- [ ] **Step 1: Add a history parser and wire it into `handleChat`**

In `backend/src/server/index.ts`, add near `normalizeUndoMessage` (around line 218) — this file has no dedicated test suite (server-level behavior isn't unit-tested anywhere in this repo; coverage lives at the service level per Tasks 1/2/4/5), so this step is verified manually in Task 6:

```typescript
import type { HistoryEntry } from "../services/openai/prompts.ts";

function parseHistory(raw: string | undefined): HistoryEntry[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((entry): entry is HistoryEntry =>
        !!entry &&
        typeof entry === "object" &&
        (entry.role === "user" || entry.role === "assistant") &&
        typeof entry.text === "string"
      )
      .slice(-20);
  } catch {
    return [];
  }
}
```

(Add the `HistoryEntry` import to the existing `import type { ChatPromptOptions } from "../services/openai/prompts.ts";` line — combine into one import.)

In `handleChat`, after the existing field reads (around line 227, right after `additionalDetails`):

```typescript
  const history = parseHistory(body.fields.history);
```

Then add `history` to the `chatEdit` call (around line 274-282):

```typescript
    const result = await chatEdit({
      sourceText,
      additionalDetails,
      currentMermaid: mermaidCode,
      previousMermaid: previousMermaidCode,
      actionType: resolvedAction,
      userMessage: message,
      attachmentContext,
      history
    });
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/server/index.ts
git commit -m "feat: parse and forward chat history in handleChat"
```

---

### Task 4: `VLLMClient` captures `usage` from the LLM response

**Files:**
- Modify: `backend/src/infrastructure/llm/client.ts`
- Test: `backend/tests/infrastructure/llm/client.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/infrastructure/llm/client.test.ts` (after the existing `completeJson` tests):

```typescript
test("completeJson: exposes usage from response on client.lastUsage", async () => {
  const payload = { mermaid: "flowchart LR\nA-->B", message: "ok" };
  const { url, close } = mockLlmServer({
    choices: [{ message: { content: JSON.stringify(payload) } }],
    usage: { prompt_tokens: 120, completion_tokens: 30, total_tokens: 150 },
  });
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    await client.completeJson("x", {}, "X");
    assert.deepEqual(client.lastUsage, { promptTokens: 120, completionTokens: 30, totalTokens: 150 });
  } finally { close(); }
});

test("completeText: usage is undefined when response omits it", async () => {
  const { url, close } = mockLlmServer(llmResponse("flowchart LR\nA --> B"));
  try {
    const client = new VLLMClient({ url, model: "test", responseFormatMode: "none" });
    await client.completeText("make a diagram");
    assert.equal(client.lastUsage, undefined);
  } finally { close(); }
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test backend/tests/infrastructure/llm/client.test.ts`
Expected: FAIL — `lastUsage` does not exist on `VLLMClient`.

- [ ] **Step 3: Implement usage capture in `client.ts`**

Add an exported `LLMUsage` type near the top of `backend/src/infrastructure/llm/client.ts` (after `ResponseFormatMode`):

```typescript
export interface LLMUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
}
```

Add a `lastUsage` field to the class (next to the other public readonly fields):

```typescript
export class VLLMClient {
  readonly model: string;
  readonly timeoutMs: number;
  readonly temperature: number;
  readonly seed?: number;
  responseFormatMode: ResponseFormatMode;
  lastUsage: LLMUsage | undefined;
  protected readonly baseUrl: string;
  protected readonly headers: Record<string, string>;
  protected readonly dispatcher: Agent | undefined;
```

Update `_post`'s return type and body to parse and return `usage`:

```typescript
  private async _post(
    messages: { role: string; content: string }[],
    responseFormat?: unknown,
  ): Promise<{ content: string; reasoningContent: string; usage: LLMUsage | undefined }> {
```

Inside `_post`, where the response JSON is parsed:

```typescript
      const data = await response.json() as {
        choices: { message: { content?: string; reasoning_content?: string } }[];
        usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
      };
      const msg = data.choices[0]?.message ?? {};
      const usage: LLMUsage | undefined = data.usage
        ? {
            promptTokens: data.usage.prompt_tokens ?? 0,
            completionTokens: data.usage.completion_tokens ?? 0,
            totalTokens: data.usage.total_tokens ?? 0,
          }
        : undefined;
      return {
        content: msg.content ?? "",
        reasoningContent: (msg as Record<string, string>).reasoning_content ?? "",
        usage,
      };
```

Update `completeText` and `completeJson` to stash `usage` on `this.lastUsage`:

```typescript
  async completeText(prompt: string, system?: string): Promise<string> {
    const messages: { role: string; content: string }[] = [];
    if (system) messages.push({ role: "system", content: system });
    messages.push({ role: "user", content: prompt });
    const { content, usage } = await this._post(messages);
    this.lastUsage = usage;
    return _extractMermaid(_stripThinkTags(content));
  }
```

```typescript
    const { content, reasoningContent, usage } = await this._post(messages, responseFormat);
    this.lastUsage = usage;
    const raw = content.includes("{") ? content : (reasoningContent.includes("{") ? reasoningContent : content);
    return _extractJson(_stripThinkTags(raw));
```

(that last snippet replaces the equivalent two lines at the end of `completeJson`, inserting the `this.lastUsage = usage;` line between them)

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test backend/tests/infrastructure/llm/client.test.ts`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `npm test`
Expected: PASS — no other test in the repo asserts on `_post`'s return shape directly, so widening it is additive.

- [ ] **Step 6: Commit**

```bash
git add backend/src/infrastructure/llm/client.ts backend/tests/infrastructure/llm/client.test.ts
git commit -m "feat: capture LLM token usage on VLLMClient.lastUsage"
```

---

### Task 5: `chatEdit` returns usage; `handleChat` includes it in the response

**Files:**
- Modify: `backend/src/services/openai/index.ts`
- Modify: `backend/src/server/index.ts`
- Test: `backend/tests/services/openai/chatEdit.test.ts`

- [ ] **Step 1: Write the failing test**

In `backend/tests/services/openai/chatEdit.test.ts`, extend the local `mockLlmServer` helper to allow an optional `usage` in the handler's return value:

```typescript
function mockLlmServer(
  handler: (body: unknown) => {
    content: string;
    usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  },
): { url: string; close: () => void } {
  const server = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      const parsed = raw ? JSON.parse(raw) : {};
      const { content, usage } = handler(parsed);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({
        choices: [{ message: { content, role: "assistant" } }],
        ...(usage ? { usage } : {}),
      }));
    });
  });
  server.listen(0);
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, close: () => server.close() };
}
```

Add a new test after the existing two:

```typescript
test("chatEdit: propagates token usage from the LLM response", async () => {
  const { url, close } = mockLlmServer(() => ({
    content: JSON.stringify({ mermaid: "flowchart LR\nA --> B", message: "Готово." }),
    usage: { prompt_tokens: 200, completion_tokens: 40, total_tokens: 240 },
  }));
  const originalUrl = config.llmUrl;
  const originalMode = config.llmResponseFormatMode;
  config.llmUrl = url;
  config.llmResponseFormatMode = "none";
  try {
    const result = await chatEdit(opts());
    assert.deepEqual(result.usage, { promptTokens: 200, completionTokens: 40, totalTokens: 240 });
  } finally {
    close();
    config.llmUrl = originalUrl;
    config.llmResponseFormatMode = originalMode;
  }
});
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `node --test backend/tests/services/openai/chatEdit.test.ts`
Expected: FAIL — `result.usage` is `undefined`, assertion mismatch.

- [ ] **Step 3: Implement usage capture in `chatEdit`**

In `backend/src/services/openai/index.ts`, import `LLMUsage`:

```typescript
import { VLLMClient, type LLMUsage } from "../../infrastructure/llm/client.ts";
```

Extend `ChatEditResult`:

```typescript
export interface ChatEditResult {
  mermaidCode: string;
  message: string;
  usage: LLMUsage | undefined;
}
```

In `chatEdit`, capture usage from the client that produced the successful response, and return it:

```typescript
export async function chatEdit(opts: ChatPromptOptions): Promise<ChatEditResult> {
  const prompt = buildChatPrompt(opts);
  let capturedUsage: LLMUsage | undefined;

  const raw = await completeJsonWithFallback(
    (mode) => new VLLMClient({
      url: config.llmUrl,
      model: config.llmModel,
      apiKey: config.llmApiKey,
      timeoutMs: config.llmTimeoutMs,
      temperature: config.llmTemperature,
      seed: config.llmSeed,
      responseFormatMode: mode,
      insecureTls: config.llmInsecureTls
    }),
    config.llmResponseFormatMode,
    async (client) => {
      const result = await client.completeJson(prompt, CHAT_OUTPUT_SCHEMA, "ChatOutput");
      capturedUsage = client.lastUsage;
      return result;
    }
  );

  let mermaidCode = String(raw["mermaid"] ?? "").trim();
  const message = String(raw["message"] ?? "").trim();

  const validation = validateMermaid(mermaidCode);
  if (!validation.ok) {
    const repairClient = makeClient();
    try {
      const repaired = await repairClient.completeText(
        buildRepairPrompt(mermaidCode, validation.reason, [])
      );
      const revalidation = validateMermaid(repaired);
      if (revalidation.ok) {
        mermaidCode = repaired;
      } else {
        throw new Error("Repair failed: " + revalidation.reason);
      }
    } catch {
      throw new LLMError("SCHEMA_MISMATCH", "Generated Mermaid failed validation after repair");
    }
  }

  return { mermaidCode, message, usage: capturedUsage };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test backend/tests/services/openai/chatEdit.test.ts`
Expected: PASS (all three tests in the file)

- [ ] **Step 5: Include usage in the `/api/chat` response**

In `backend/src/server/index.ts`, `handleChat`'s success branch (around line 283-290):

```typescript
    return sendJson(response, 200, {
      ok: true,
      result: {
        mermaidCode: result.mermaidCode,
        previousMermaidCode: mermaidCode,
        message: result.message,
        usage: result.usage
      }
    });
```

- [ ] **Step 6: Run the full backend suite**

Run: `npm test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/services/openai/index.ts backend/src/server/index.ts backend/tests/services/openai/chatEdit.test.ts
git commit -m "feat: propagate LLM token usage through chatEdit to /api/chat response"
```

---

### Task 6: Frontend sends a windowed chat history on every chat request

**Files:**
- Modify: `frontend/src/main.ts`

There is no automated test framework wired up for the frontend in this repo (verified: no test runner in `package.json` covers `frontend/src`, coverage is backend-only via `node --test`). This task is verified manually in Step 3.

- [ ] **Step 1: Add a history window constant**

In `frontend/src/main.ts`, near the existing `pendingActionType` declaration (around line 47):

```typescript
const CHAT_HISTORY_WINDOW = 10;
```

- [ ] **Step 2: Capture and send the history window in `sendChat`**

In `sendChat` (around line 857-928), the `userMessage` object is built at lines 864-871, then pushed onto `state.result.chat` at line 877. Capture the history window from the transcript **before** that push, so it only contains prior turns, not the message being sent:

```typescript
  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    text: text || (attachments.length === 1 ? "Прикреплён файл" : `Прикреплено файлов: ${attachments.length}`),
    createdAt: new Date().toISOString(),
    attachment: attachments[0],
    attachments
  };

  const historyWindow = state.result.chat
    .slice(-CHAT_HISTORY_WINDOW)
    .map((entry) => ({ role: entry.role, text: entry.text }));

  const shouldScroll = isMessagesNearBottom();
```

Then, where the `FormData` is built (around line 886-893), add the serialized history:

```typescript
    const form = new FormData();
    form.set("mermaidCode", state.result.mermaidCode);
    form.set("previousMermaidCode", state.previousMermaidCode ?? "");
    form.set("message", text);
    form.set("actionType", actionType);
    form.set("sourceText", state.result.sourceText ?? "");
    form.set("additionalDetails", state.result.details ?? "");
    form.set("history", JSON.stringify(historyWindow));
    if (attachmentFile) form.set("file", attachmentFile);
```

- [ ] **Step 3: Manually verify end to end**

Run: `npm run build && npm start` (or `npm run dev`), open the app in a browser, upload a source file, send 2-3 chat edits in a row, then click "Выделить основной путь".

Expected: in the browser Network tab, each `/api/chat` request's form data includes a `history` field containing a JSON array with the prior turns (role/text pairs, growing up to 10 entries as the conversation continues). The highlighted-path response should now reflect awareness of prior edits (e.g. it doesn't reset styling applied in earlier turns) — full correctness of `HIGHLIGHT_MAIN_PATH` itself depends on Веха 2 (prompt sync), so judge this step only on "history is being sent and the backend responds normally", not on the highlight rendering being perfect yet.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.ts
git commit -m "feat: send windowed chat history with every chat request"
```

---

## Self-review notes

- Spec coverage: Веха 0 spec items were "прокинуть историю сообщений" (Tasks 1, 3, 6) and "usage-трекинг" (Tasks 4, 5) — both covered.
- `history` is a required field on `ChatPromptOptions` (not optional) so every call site must pass it explicitly — this is intentional: it forces `handleChat` and any future caller to make a conscious choice rather than silently sending no history.
- `ChatEditResult.usage` is `LLMUsage | undefined` (not optional key) so callers must handle the "no usage" case explicitly rather than it being an easy-to-miss optional chain.
