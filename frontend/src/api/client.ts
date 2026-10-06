import type { ApiError } from "../types/index.ts";
import type { ChatResult, DiagramResult, PendingTurn } from "../../../shared/types/index.ts";
import { createId } from "../utils/id.ts";
import { forgetPendingRequest, loadPendingRequest, savePendingRequest } from "../state/pendingRequest.ts";

const POLL_INTERVAL_MS = 2000;
const TEMPORARY_HTTP_ERRORS = new Set([502, 503, 504]);
type Accepted = { status: "processing"; sessionId: string; requestId: string };
type TurnPayload<T> = { ok?: boolean; error?: ApiError; result?: T } & Partial<Accepted>;

// Proxy failures can have HTML bodies. Surface a safe API error instead of
// exposing a JSON parser exception to the user.
async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw { code: "network-error", message: "Сервер вернул некорректный ответ" } as ApiError;
  }
}

export async function getConfig(): Promise<{ productHomeUrl: string }> {
  const response = await fetch("api/config");
  const payload = await parseJsonResponse(response) as { productHomeUrl?: string };
  return { productHomeUrl: payload.productHomeUrl || "http://localhost:3000/" };
}

export async function generateDiagram(form: FormData, onAccepted?: (pending: PendingTurn) => void, signal?: AbortSignal): Promise<DiagramResult> {
  form.set("requestId", String(form.get("requestId") || createId()));
  return submitAndPoll<DiagramResult>("generate", "api/generate", form, onAccepted, signal);
}

export async function sendChatMessage(sessionId: string, form: FormData, onAccepted?: (pending: PendingTurn) => void, signal?: AbortSignal): Promise<ChatResult> {
  form.set("sessionId", sessionId);
  return submitAndPoll<ChatResult>("chat", "api/chat", form, onAccepted, signal);
}

async function submitAndPoll<T>(kind: PendingTurn["kind"], url: string, body: FormData, onAccepted?: (pending: PendingTurn) => void, signal?: AbortSignal): Promise<T> {
  await savePendingRequest(kind, body);
  let polling = false;
  try {
    signal?.throwIfAborted();
    const response = await fetch(url, { method: "POST", body, signal });
    const payload = await parseJsonResponse(response) as TurnPayload<T>;
    signal?.throwIfAborted();
    if (response.status === 202 && payload.status === "processing" && payload.sessionId && payload.requestId) {
      const pending = { kind, sessionId: payload.sessionId, requestId: payload.requestId };
      onAccepted?.(pending);
      polling = true;
      return await pollTurn<T>(pending, () => retryTurn<T>(kind, body, signal), signal);
    }
    if (!response.ok || payload.ok === false) throw payload.error;
    return (payload.ok ? payload.result : payload) as T;
  } finally {
    // Once accepted, pollTurn owns cleanup and preserves input when its
    // observer is cancelled. Before acceptance there is no pending turn to
    // resume, so do not leave an unattached upload in storage.
    if (!polling) await forgetPendingRequest(String(body.get("requestId")));
  }
}

async function retryTurn<T>(kind: PendingTurn["kind"], body: FormData, signal?: AbortSignal): Promise<T | undefined> {
  let response: Response;
  try {
    response = await fetch(`api/${kind}`, { method: "POST", body, signal });
  } catch {
    signal?.throwIfAborted();
    return undefined;
  }
  if (TEMPORARY_HTTP_ERRORS.has(response.status)) return undefined;
  const payload = await parseJsonResponse(response) as TurnPayload<T>;
  if (response.status === 202) return undefined;
  if (response.ok && payload.ok !== false) return (payload.ok ? payload.result : payload) as T;
  if (response.status === 409 && payload.error?.code === "request-in-progress") return undefined;
  throw payload.error;
}

function waitForPoll(signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const aborted = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", aborted);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", aborted);
      resolve();
    }, POLL_INTERVAL_MS);
    signal?.addEventListener("abort", aborted, { once: true });
  });
}

export async function pollTurn<T>(pending: PendingTurn, retry?: () => Promise<T | undefined>, signal?: AbortSignal): Promise<T> {
  const path = `api/${pending.kind}/${encodeURIComponent(pending.sessionId)}/turns/${encodeURIComponent(pending.requestId)}`;
  try {
    while (true) {
      signal?.throwIfAborted();
      let response: Response;
      try {
        response = await fetch(path, { signal });
      } catch {
        signal?.throwIfAborted();
        await waitForPoll(signal);
        continue;
      }
      if (TEMPORARY_HTTP_ERRORS.has(response.status)) {
        await waitForPoll(signal);
        continue;
      }
      const payload = await parseJsonResponse(response) as { ok?: boolean; result?: T; error?: ApiError; status?: string; retryable?: boolean };
      signal?.throwIfAborted();
      if (!response.ok) throw payload.error;
      if (payload.ok) return payload.result as T;
      if (payload.ok === false) throw payload.error;
      if (payload && typeof payload === "object" && "sessionId" in payload) return payload as T;
      if (payload.status === "failed" && payload.retryable) {
        if (!retry) {
          const body = await loadPendingRequest(pending);
          if (!body) throw { code: "diagram-generation", message: "Задача прервалась. Повторите запрос." } as ApiError;
          retry = () => retryTurn<T>(pending.kind, body, signal);
        }
        const result = await retry();
        if (result !== undefined) return result;
      } else if (payload.status !== "processing") {
        throw { code: "network-error", message: "Сервер вернул неизвестное состояние" } as ApiError;
      }
      await waitForPoll(signal);
    }
  } finally {
    if (!signal?.aborted) await forgetPendingRequest(pending.requestId);
  }
}

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
