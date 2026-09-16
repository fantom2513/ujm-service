# Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the already-implemented chat-attachments feature from "written and locally green" to "verified and safely releasable": prove the Postgres-backed tests actually pass, commit the feature deliberately, fix two frontend state bugs, cap the chat proxy body size, and correct inaccurate claims in the release docs.

**Architecture:** No new backend code — the chat-attachments backend work is complete. This plan adds verification, two isolated frontend state fixes, one Nginx location block, and documentation corrections.

**Tech Stack:** TypeScript (frontend, `node --test`), Python/pytest (`backend-py/.venv`), Nginx config, Docker (for a local Postgres to run integration tests).

**Spec:**
- `docs/superpowers/specs/2026-09-09-chat-attachments-tech-debt.md`
- `docs/superpowers/specs/2026-09-16-release-readiness.md`

## Global Constraints

- Chat attachment limit is 20 MiB (`MAX_CHAT_ATTACHMENT_MB=20`), enforced by the frontend and Python backend. The Nginx limit must be **higher** than 20 MiB (see Task 4) because the multipart body carries more than the file.
- The general `/ux-architecture/api/` Nginx location keeps its 110m limit — `/api/generate` still accepts 100 MB recordings.
- Never stage with `git add -A` or `git add .`. Every commit stages files by explicit name.
- Do not commit: `package-lock.json` (untracked; the repo's lockfile is `pnpm-lock.yaml`) or `docs/superpowers/specs/2026-08-28-frontend-figma-bugfixes-design.md` (untracked, unrelated Figma batch).

### Verified baseline numbers (measured 2026-09-16, do not restate from memory)

| Suite | Command | Result |
|---|---|---|
| Frontend only | `node --test $(find frontend/tests -name '*.test.ts')` | **23 passed** |
| Legacy backend TS | `node --test $(find backend/tests -name '*.test.ts')` | 73 passed |
| Whole Node suite | `npm test` | 96 passed (23 + 73) |
| Python | `backend-py/.venv/Scripts/python.exe -m pytest tests/ -q` | 224 passed, **69 skipped** (293 collected) |

**The 69 skipped Python tests are the Postgres-backed integration tests**, skipped because Postgres is not reachable locally. They include the two tests that prove attachment context reaches the LLM and participates in the idempotency fingerprint. Task 1 exists to actually run them.

`scripts/build.mjs` is **not** a typechecker — line 44 uses `stripTypeScriptTypes(source, { mode: "strip" })`, which deletes annotations without running `tsc`. It catches syntax errors only. Call it a build check, never a typecheck.

---

## Task 1: Actually run the Postgres-backed integration tests

**Files:** none modified — verification only.

**Context:** `backend-py/tests/integration/test_chat_idempotency.py` contains `test_run_chat_passes_attachment_context_to_the_llm_prompt` and `test_same_request_id_with_different_attachment_content_conflicts` — the only automated proof of spec requirements #4 and #7. Both are currently **skipped** locally ("Postgres not reachable at postgresql+asyncpg://uxarch:uxarch@localhost:5432/uxarch"). CI (`.gitlab-ci.yml:19-52`) does provide Postgres and runs them, but this branch has not been pushed, so these tests have never been observed passing anywhere. Do not commit the feature until they are green.

- [ ] **Step 1: Start a local Postgres matching the URL the tests expect**

```bash
docker run -d --name uxarch-test-pg -p 5432:5432 \
  -e POSTGRES_USER=uxarch -e POSTGRES_PASSWORD=uxarch -e POSTGRES_DB=uxarch \
  postgres:15-alpine
```

If that image can't be pulled, use the corporate mirror: `nexus.sogaz.ru/library/postgres:15-alpine`.

- [ ] **Step 2: Wait for it to accept connections**

```bash
docker exec uxarch-test-pg pg_isready -U uxarch -d uxarch
```
Expected: `accepting connections`. Retry a few seconds if it reports "no response".

- [ ] **Step 3: Run the two attachment tests specifically**

```bash
cd backend-py && .venv/Scripts/python.exe -m pytest \
  tests/integration/test_chat_idempotency.py -v -ra \
  -k "attachment"
```
Expected: 2 passed, 0 skipped. **If either is skipped, the database is not reachable — fix that before continuing; a skip is not a pass.**

- [ ] **Step 4: Run the whole Python suite with Postgres up**

```bash
cd backend-py && .venv/Scripts/python.exe -m pytest tests/ -q -ra
```
Expected: 293 passed, 0 skipped (or a much smaller skip count). Record the exact numbers — Task 6 writes them into the release doc.

- [ ] **Step 5: Stop the container**

```bash
docker rm -f uxarch-test-pg
```

- [ ] **Step 6: If any test failed, stop and report**

Do not proceed to Task 2. A failure here means the feature is not release-ready and the plan needs revisiting.

---

## Task 2: Commit the completed chat-attachments feature as one deliberate release commit

**Files:** the full set below, staged by explicit name.

**Context:** The entire chat-attachments feature (backend + frontend + tests) currently sits uncommitted in the working tree — 15 modified and 3 new files. The later tasks touch `frontend/src/state/session.ts` and `frontend/src/main.ts`, which **already contain uncommitted feature work**; if the bugfix tasks ran first, their `git add` would silently sweep that work into a bugfix commit while leaving the backend orphaned. Committing the feature first makes every later commit clean and reviewable.

- [ ] **Step 1: Review exactly what is about to be staged**

```bash
git status --short
git diff --stat
```
Confirm the working tree matches the list in Step 2, plus the excluded files named in Global Constraints.

- [ ] **Step 2: Stage the feature files by name**

```bash
git add \
  .env.example \
  backend-py/app/api/chat.py \
  backend-py/app/config.py \
  backend-py/app/domain/chat_request.py \
  backend-py/app/services/chat/service.py \
  backend-py/app/services/files/_common.py \
  backend-py/app/services/files/extract.py \
  backend-py/tests/api/test_chat_endpoint.py \
  backend-py/tests/domain/test_chat_request.py \
  backend-py/tests/integration/test_chat_idempotency.py \
  backend-py/tests/services/files/test_extract.py \
  backend-py/tests/services/files/test_common.py \
  backend-py/tests/test_config.py \
  frontend/src/main.ts \
  frontend/src/state/session.ts \
  frontend/src/utils/chatAttachments.ts \
  frontend/tests/state/session.test.ts \
  frontend/tests/utils/chatAttachments.test.ts
```

- [ ] **Step 3: Verify nothing unintended is staged**

```bash
git status --short
```
Expected: every line above shows as staged (`M `/`A `). `package-lock.json` and `docs/superpowers/specs/2026-08-28-frontend-figma-bugfixes-design.md` must still show as untracked (`??`).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(backend-py): support file attachments in chat

POST /api/chat now reads the optional multipart 'file' field, validates
it against the chat format set (txt/docx/pdf/xlsx/csv) and the 20 MiB
limit, extracts its text, and passes it to the LLM prompt as
attachment_context. Legacy .xls is rejected outright rather than
accepted with a stub, since openpyxl cannot read OLE2/BIFF.

The idempotency fingerprint now covers attachment content (hash version
2), so reusing one requestId with a different file conflicts instead of
replaying a result produced for another file.

Parser failures no longer log tracebacks or exception messages, which
could quote fragments of the uploaded file."
```

---

## Task 3: Stop a restored chat attachment from surviving reload as a phantom file

**Files:**
- Modify: `frontend/src/state/session.ts` (`clearUnrecoverableAttachment`)
- Test: `frontend/tests/state/session.test.ts`

**Interfaces:**
- Consumes: `AppState.chatAttachment?: FileMeta`, `AppState.chatAttachments?: FileMeta[]` (`frontend/src/types/index.ts:30-31`); `FileMeta = { name: string; format: string; size: number }` (`shared/types/index.ts:22-26`).
- Produces: nothing new — `clearUnrecoverableAttachment` keeps its signature `(state: AppState) => AppState`, called only from `loadState()`.

**Context:** `clearUnrecoverableAttachment` already clears `start.file`/`start.recording` on reload, because a `File` cannot survive `JSON.stringify` into `sessionStorage` — what comes back is metadata for an object that no longer exists. `chatAttachment`/`chatAttachments` (the file attached inside the chat panel, after a diagram exists) are the same kind of value with the same problem, and the function never touches them. After a reload the chat shows an attachment card with nothing behind it: `sendChat()` reads `chatFiles[0]`, a module-level array that is always empty after a reload, so the "attached" file is silently never sent.

- [ ] **Step 1: Write the failing test**

Append to `frontend/tests/state/session.test.ts` (same `sessionStorage` stub pattern as the first test in the file):

```typescript
test("loadState clears a restored chat attachment because its File object cannot survive sessionStorage", () => {
  const originalStorage = globalThis.sessionStorage;
  const values = new Map<string, string>();
  globalThis.sessionStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
    clear: () => values.clear(),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() {
      return values.size;
    }
  };

  try {
    const state = structuredClone(defaultState);
    state.page = "result";
    state.result = {
      sessionId: "session-a",
      title: "Diagram",
      mermaidCode: "flowchart LR\nA-->B",
      sourceText: "spec",
      sourceContext: { type: "text-file", title: "spec", description: "text" },
      chat: [],
      warnings: []
    };
    state.chatAttachment = { name: "notes.txt", format: "txt", size: 10 };
    state.chatAttachments = [state.chatAttachment];

    saveState(state);
    const restored = loadState();

    assert.equal(restored.chatAttachment, undefined);
    assert.equal(restored.chatAttachments, undefined);
  } finally {
    globalThis.sessionStorage = originalStorage;
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test frontend/tests/state/session.test.ts`
Expected: FAIL — `restored.chatAttachment` is still `{ name: "notes.txt", ... }`, not `undefined`.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/state/session.ts`, replace:

```typescript
function clearUnrecoverableAttachment(state: AppState): AppState {
  if (state.start.file || state.start.recording) {
    state.start.file = undefined;
    state.start.recording = undefined;
    if (state.start.error?.field === "attachment") state.start.error = undefined;
  }
  return state;
}
```

with:

```typescript
function clearUnrecoverableAttachment(state: AppState): AppState {
  if (state.start.file || state.start.recording) {
    state.start.file = undefined;
    state.start.recording = undefined;
    if (state.start.error?.field === "attachment") state.start.error = undefined;
  }
  // Same reasoning for the chat-panel attachment: chatFiles (the module-level
  // File array in main.ts) is always empty after a reload, so a restored
  // chatAttachment is a card the user can see but never send.
  if (state.chatAttachment || state.chatAttachments) {
    state.chatAttachment = undefined;
    state.chatAttachments = undefined;
  }
  return state;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test $(find frontend/tests -name '*.test.ts')`
Expected: **24 passed** (the 23 baseline plus this one).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/state/session.ts frontend/tests/state/session.test.ts
git commit -m "fix(frontend): clear a restored chat attachment on reload"
```

---

## Task 4: Reset the chat composer's validation error when starting a new diagram

**Files:**
- Modify: `frontend/src/main.ts` (`#modal-confirm` click handler)

**Interfaces:**
- Consumes: module-level `let chatInputError = ""` (`frontend/src/main.ts:40`), read by `chatPanel()` (line 337), mutated by `syncChatTextarea` (792), `addChatFiles` (1114), `removeChatFile` (1129).
- Produces: nothing new.

**Context:** That handler already resets `selectedFile`, `sourceFile`, `chatFiles`, and `messageFiles` — all module-level values `resetState()` cannot reach, as its existing comment explains. `chatInputError` is the same kind of value and is not reset. A stale validation error ("Файл уже добавлен", "Этот формат файла не поддерживается") can therefore still be displayed in the composer after the user starts a brand-new diagram.

- [ ] **Step 1: Make the change**

In the `#modal-confirm` click handler, change:

```typescript
    selectedFile = undefined;
    sourceFile = undefined;
    chatFiles = [];
    messageFiles.clear();
```

to:

```typescript
    selectedFile = undefined;
    sourceFile = undefined;
    chatFiles = [];
    chatInputError = "";
    messageFiles.clear();
```

- [ ] **Step 2: Run the build as a syntax/build check (NOT a typecheck — see Global Constraints)**

Run: `node scripts/build.mjs`
Expected: `Frontend built into frontend/dist`, exit 0.

- [ ] **Step 3: Verify live in the browser**

No automated test covers `main.ts` — no test file in this repo imports it, and the established precedent for `main.ts` fixes is live verification. Use the `run` skill to start the app, then:
1. Generate a diagram.
2. In chat, attach the same file twice (or an `.xls`) to trigger `chatInputError`.
3. Leaving the error visible, click "Создать новую схему" and confirm in the modal.
4. Generate a second diagram and open its chat panel.
5. Confirm no stale error text is present.

Record the observed result. If the error still appears, the fix is wrong — report rather than patching blindly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.ts
git commit -m "fix(frontend): reset chat composer error when starting a new diagram"
```

---

## Task 5: Cap the `/api/chat` proxy body size

**Files:**
- Modify: `frontend/nginx.conf`

**Context:** `frontend/nginx.conf:5-18` has one `location /ux-architecture/api/` with `client_max_body_size 110m`, sized for 100 MB recordings on `/api/generate`. `/api/chat` inherits it, so an oversized chat body is only rejected later, by Python.

**Why 21m and not 20m:** `client_max_body_size` applies to the **whole multipart body**, not the file part. `main.ts:952-957` puts `mermaidCode` (an entire diagram, not a few bytes), `message`, `actionType`, and `requestId` into the same form, and `client.ts:29` adds `sessionId`, plus MIME boundaries. Both the frontend (`file.size > CHAT_ATTACHMENT_MAX_BYTES`) and Python (`len(content) > max_chat_attachment_bytes`) use a strict `>`, so a file of **exactly** 20 MiB is legal — with `20m` Nginx would reject that legal request outright. `21m` leaves 1 MiB of headroom for the other fields; the exact 20 MiB file limit stays where it belongs, in Python.

The frontend calls the relative URL `api/chat` (`client.ts:29`) from a page served at `/ux-architecture/`, which resolves to `/ux-architecture/api/chat` — so an exact-match location is correct, and exact matches win over prefix matches regardless of declaration order.

- [ ] **Step 1: Make the change**

Insert before the existing `location /ux-architecture/api/` block:

```nginx
    location = /ux-architecture/api/chat {
        # Chat attachments are capped at 20 MiB by the application
        # (app.config.max_chat_attachment_bytes). 21m, not 20m: this limit
        # covers the whole multipart body -- mermaidCode, message, actionType,
        # requestId, sessionId and MIME boundaries ride along with the file, so
        # 20m would reject a legal request carrying a file of exactly 20 MiB.
        # The general 110m limit below stays for 100 MB recordings on
        # /api/generate.
        client_max_body_size 21m;
        proxy_pass http://ux-architecture-backend:8001/api/chat;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
```

Leave the existing `location /ux-architecture/api/` block unchanged.

- [ ] **Step 2: Validate the config**

```bash
docker run --rm -v "/c/work/ujm-service/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27-alpine nginx -t
```
Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`

(The `proxy_pass` upstream name won't resolve outside Compose; `nginx -t` checks syntax, which is what this step verifies.)

- [ ] **Step 3: Commit**

```bash
git add frontend/nginx.conf
git commit -m "fix(deploy): cap the /api/chat proxy body size at 21m"
```

---

## Task 6: Correct the release documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-chat-attachments-tech-debt.md`
- Modify: `docs/superpowers/specs/2026-09-16-release-readiness.md`

**Context — three separate corrections, one of them undoing an earlier mistake:**

1. **Revert an incorrect "fix" to the historical spec.** Line 92-93 currently reads "Frontend tests pass (13 tests in `session.test.ts` and `chatAttachments.test.ts`; 96 across the full suite)". This edit was wrong: the frontend suite is **23 tests**, which is what the document said before. 13 was a miscount of two files, and 96 is the whole Node suite (23 frontend + 73 legacy backend TS), a different metric. Restore the correct number.
2. **The "293 tests passed" claim is wrong in both documents.** The local run was 224 passed / 69 skipped; the 69 skips are exactly the Postgres-backed integration tests, so `release-readiness.md`'s "including API and Postgres-backed chat idempotency tests" asserted the opposite of what happened. After Task 1, state the real numbers from that run.
3. **The manual-QA provenance claim.** `release-readiness.md:51-53` says manual browser checks "already confirmed" three fixes. This was an automated agent run against the local app, not a human QA session and not the test environment, and nothing is recorded in `docs/deployment-smoke-results.md` (an unfilled template).

- [ ] **Step 1: Restore the correct frontend test count in the historical spec**

In `docs/superpowers/specs/2026-09-09-chat-attachments-tech-debt.md`, replace:
```
- Frontend tests pass (13 tests in `session.test.ts` and `chatAttachments.test.ts`;
  96 across the full suite) and the production frontend build succeeds.
```
with:
```
- Frontend tests pass (23 tests) and the production frontend build succeeds.
```

- [ ] **Step 2: Correct the Python test claim in the historical spec**

Replace:
```
- Python unit, API, and Postgres-backed integration tests pass (293 tests).
```
with the real figures from Task 1 Step 4, in this shape:
```
- Python unit, API, and Postgres-backed integration tests pass (<N> passed with
  Postgres available; without a local Postgres, <M> integration tests skip).
```

- [ ] **Step 3: Correct the same claim in the release doc**

In `docs/superpowers/specs/2026-09-16-release-readiness.md`, replace:
```
- Python backend: 293 tests passed, including API and Postgres-backed chat
  idempotency tests.
```
with the Task 1 figures, noting explicitly that the Postgres-backed tests were run with a local Postgres container (they skip when one is not reachable).

- [ ] **Step 4: Correct the manual-QA provenance**

Replace:
```
- Manual browser checks already confirmed that an invalid initial upload is not
  shown twice, an error-toast close button works, and a page reload clears the
  initial-upload state.
```
with:
```
- An automated browser check against a local instance confirmed that an invalid
  initial upload is not shown twice, the error-toast close button works, and a
  page reload clears the initial-upload state. This was not a human QA session
  and was not run against the test environment; nothing is recorded for it in
  `docs/deployment-smoke-results.md`. Repeat these three checks on the test
  environment as part of the smoke test below before treating them as release
  evidence.
```

- [ ] **Step 5: Extend the smoke-test list**

Inside item 3 of "Required before production deployment", add to the bullet list:
```
  - reload the page after an initial-upload error and confirm it is not shown
    twice and no stale attachment appears as still attached;
  - attach a file in chat, reload, and confirm the chat attachment card is gone
    rather than shown as still attached;
  - trigger the generation-error toast and confirm its close button clears it.
```

- [ ] **Step 6: Record the two fixed bugs**

Under "Completed changes" → "Frontend stability", add:
```
- A restored chat attachment no longer survives a page reload as a phantom card
  with no file behind it; it is cleared like `start.file`/`start.recording`.
- Starting a new diagram clears a stale chat-composer validation error instead
  of carrying it into the next diagram's chat panel.
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-09-09-chat-attachments-tech-debt.md \
        docs/superpowers/specs/2026-09-16-release-readiness.md \
        docs/superpowers/plans/2026-09-16-release-hardening.md
git commit -m "docs: correct test counts and QA provenance in the release specs"
```

---

## Task 7: Final release gate

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm the excluded files were never committed**

```bash
git status --short
git log --stat -6 | grep -E "package-lock|2026-08-28-frontend-figma"
```
Expected: `git status` still lists `package-lock.json` and the Figma spec as `??`; the `grep` prints nothing.

- [ ] **Step 2: Run everything one final time**

```bash
docker run -d --name uxarch-test-pg -p 5432:5432 \
  -e POSTGRES_USER=uxarch -e POSTGRES_PASSWORD=uxarch -e POSTGRES_DB=uxarch \
  postgres:15-alpine
cd backend-py && .venv/Scripts/python.exe -m pytest tests/ -q -ra; cd ..
npm test
node scripts/build.mjs
docker rm -f uxarch-test-pg
```
Expected: Python all green with no Postgres skips; Node 97 passed (96 baseline + the Task 3 test); build exits 0.

- [ ] **Step 3: Review the branch**

```bash
git log --oneline origin/main..HEAD
git diff origin/main..HEAD --stat
```
Confirm the commits are the four from Tasks 2-6 and the file list is exactly what was intended.

- [ ] **Step 4: Report what remains before production**

These are deployment actions outside this repo and cannot be completed from here — state them plainly rather than marking them done:
- `PRODUCT_HOME_URL` must be set in the `ENV_TEST` and `ENV_PROD` GitLab CI/CD variables (they are written to `.env` at deploy time, `.gitlab-ci.yml:86,106,124,151`). Verify after deploy with `curl -s https://<host>/ux-architecture/api/config` and confirm the returned `productHomeUrl` is the real CX Copilot URL, not `http://localhost:3000/`.
- The live-LLM smoke test from `release-readiness.md` item 3, with results written into `docs/deployment-smoke-results.md`.
