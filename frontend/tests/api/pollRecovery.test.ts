import test from "node:test";
import assert from "node:assert/strict";
import { sendChatMessage, generateDiagram, pollTurn } from "../../src/api/client.ts";
import { savePendingRequest, loadPendingRequest, forgetPendingRequest } from "../../src/state/pendingRequest.ts";
import { memoryIndexedDb } from "../helpers/indexedDb.ts";

const result = { sessionId: "s1", mermaidCode: "flowchart LR\nA-->B", message: "Done" };
const accepted = { status: "processing", sessionId: "s1", requestId: "r1" };
const expired = { status: "failed", retryable: true };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

for (const outage of ["network", 502, 503, 504] as const) {
  test(`takeover polling survives a retry POST ${outage} outage`, async () => {
    const originalFetch = globalThis.fetch;
    const originalTimer = globalThis.setTimeout;
    let calls = 0;
    const posts: FormData[] = [];
    globalThis.setTimeout = ((callback: () => void) => { queueMicrotask(callback); return 1; }) as typeof setTimeout;
    globalThis.fetch = async (_path, init) => {
      calls++;
      if (init?.method === "POST") posts.push(init.body as FormData);
      if (calls === 1) return response(accepted, 202);
      if (calls === 2 || calls === 4) return response(expired);
      if (calls === 3) {
        if (outage === "network") throw new TypeError("offline");
        return new Response("gateway unavailable", { status: outage });
      }
      if (calls === 5) return response(accepted, 202);
      return response(result);
    };
    try {
      const form = new FormData();
      form.set("requestId", "r1"); form.set("message", "Change B");
      const actual = await sendChatMessage("s1", form);
      assert.deepEqual(actual, result);
      assert.equal(posts.length, 3);
      for (const post of posts) assert.equal(post.get("requestId"), "r1");
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.setTimeout = originalTimer;
    }
  });
}

for (const kind of ["chat", "generate"] as const) {
  test(`reload recovers expired ${kind} with the original request and uploaded bytes`, async () => {
    const originalFetch = globalThis.fetch;
    const originalTimer = globalThis.setTimeout;
    const originalDb = globalThis.indexedDB;
    globalThis.indexedDB = memoryIndexedDb();
    globalThis.setTimeout = ((callback: () => void) => { queueMicrotask(callback); return 1; }) as typeof setTimeout;
    let firstPoll: (value: Response) => void;
    let acceptedSeen: () => void;
    const acceptedPromise = new Promise<void>(resolve => { acceptedSeen = resolve; });
    let calls = 0;
    let replayForm: FormData | undefined;
    globalThis.fetch = async (_path, init) => {
      calls++;
      if (calls === 1) return response(accepted, 202);
      if (calls === 2) return new Promise<Response>(resolve => { firstPoll = resolve; });
      if (calls === 3) return response(expired);
      if (init?.method === "POST") { replayForm = init.body as FormData; return response(accepted, 202); }
      return response(result);
    };
    const form = new FormData();
    form.set("requestId", "r1"); form.set("message", "Change B"); form.set("actionType", "FREEFORM");
    form.set("file", new Blob(["attachment contents"], {type: "text/plain"}), "notes.txt");
    form.set("sourceType", "text-file"); form.set("details", "Keep all steps");
    const original = kind === "chat" ? sendChatMessage("s1", form, () => acceptedSeen()) : generateDiagram(form, () => acceptedSeen());
    try {
      await acceptedPromise;
      await new Promise<void>(resolve => setImmediate(resolve));
      const restored = await pollTurn({kind, sessionId: "s1", requestId: "r1"});
      assert.deepEqual(restored, result);
      assert.equal(replayForm?.get("requestId"), "r1");
      if (kind === "chat") assert.equal(replayForm?.get("sessionId"), "s1");
      else { assert.equal(replayForm?.get("sourceType"), "text-file"); assert.equal(replayForm?.get("details"), "Keep all steps"); }
      assert.equal(replayForm?.get("message"), "Change B");
      const file = replayForm?.get("file") as File;
      assert.equal(file.name, "notes.txt");
      assert.equal(await file.text(), "attachment contents");
      assert.equal(await loadPendingRequest({kind, sessionId: "s1", requestId: "r1"}), undefined);
    } finally {
      firstPoll!(response(result));
      await original;
      globalThis.fetch = originalFetch;
      globalThis.setTimeout = originalTimer;
      globalThis.indexedDB = originalDb;
    }
  });

}

for (const phase of ["fetch", "interval"] as const) {
  test(`cancelling polling during ${phase} preserves input for the next observer`, async () => {
    const originalFetch = globalThis.fetch;
    const originalDb = globalThis.indexedDB;
    globalThis.indexedDB = memoryIndexedDb();
    const pending = {kind: "chat" as const, sessionId: "s1", requestId: "r1"};
    const form = new FormData(); form.set("requestId", "r1"); form.set("sessionId", "s1"); form.set("message", "Change");
    await savePendingRequest("chat", form);
    let calls = 0;
    const controller = new AbortController();
    globalThis.fetch = async (_path, init) => {
      calls++;
      if (phase === "interval") return response({status: "processing"});
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason), {once: true});
      });
    };
    try {
      const observed = pollTurn(pending, undefined, controller.signal);
      await new Promise<void>(resolve => setImmediate(resolve));
      controller.abort();
      await assert.rejects(observed, {name: "AbortError"});
      assert.equal(calls, 1);
      assert.equal((await loadPendingRequest(pending))?.get("message"), "Change");
    } finally {
      await forgetPendingRequest("r1");
      globalThis.fetch = originalFetch; globalThis.indexedDB = originalDb;
    }
  });
}

test("a stored terminal failure is surfaced without retry and removes its saved input", async () => {
  const originalFetch = globalThis.fetch;
  const originalDb = globalThis.indexedDB;
  globalThis.indexedDB = memoryIndexedDb();
  const pending = {kind: "chat" as const, sessionId: "s1", requestId: "r1"};
  const form = new FormData(); form.set("requestId", "r1"); form.set("sessionId", "s1");
  await savePendingRequest("chat", form);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response({ok: false, error: {code: "diagram-generation", message: "Failed"}}); };
  try {
    await assert.rejects(pollTurn(pending), error => error.code === "diagram-generation");
    assert.equal(calls, 1);
    assert.equal(await loadPendingRequest(pending), undefined);
  } finally {
    globalThis.fetch = originalFetch; globalThis.indexedDB = originalDb;
  }
});

test("reload does not resend an attachment belonging to another session", async () => {
  const originalFetch = globalThis.fetch;
  const originalDb = globalThis.indexedDB;
  globalThis.indexedDB = memoryIndexedDb();
  const form = new FormData(); form.set("requestId", "r1"); form.set("sessionId", "other-session");
  await savePendingRequest("chat", form);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response(expired); };
  try {
    await assert.rejects(pollTurn({kind: "chat", sessionId: "s1", requestId: "r1"}), error => error.code === "diagram-generation");
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch; globalThis.indexedDB = originalDb;
  }
});

test("cancelling before acceptance removes input that has no resumable pending turn", async () => {
  const originalFetch = globalThis.fetch;
  const originalDb = globalThis.indexedDB;
  globalThis.indexedDB = memoryIndexedDb();
  const controller = new AbortController();
  let started: () => void;
  const startedPromise = new Promise<void>(resolve => { started = resolve; });
  globalThis.fetch = async (_path, init) => {
    started();
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal!.reason), {once: true});
    });
  };
  const form = new FormData(); form.set("requestId", "r1"); form.set("message", "Change");
  try {
    const submitted = sendChatMessage("s1", form, undefined, controller.signal);
    await startedPromise;
    controller.abort();
    await assert.rejects(submitted, {name: "AbortError"});
    assert.equal(await loadPendingRequest({kind: "chat", sessionId: "s1", requestId: "r1"}), undefined);
  } finally {
    globalThis.fetch = originalFetch; globalThis.indexedDB = originalDb;
  }
});
