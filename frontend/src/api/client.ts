import type { ApiError } from "../types/index.ts";
import type { ChatResult, DiagramResult, PendingTurn } from "../../../shared/types/index.ts";
import { createId } from "../utils/id.ts";

const POLL_INTERVAL_MS = 2000;
type Accepted = { status: "processing"; sessionId: string; requestId: string };

// A non-JSON response body (an HTML error page from a proxy/gateway on a
// 502/504, an empty body, etc.) makes response.json() throw a raw
// SyntaxError like `Unexpected token '<', "<!DOCTYPE "... is not valid
// JSON`. Left uncaught, that message goes straight to the user instead of
// something readable -- wrap it into a proper ApiError shape.
async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    const error: ApiError = { code: "network-error", message: "Сервер вернул некорректный ответ" };
    throw error;
  }
}

export async function getConfig(): Promise<{ productHomeUrl: string }> {
  const response = await fetch("api/config");
  const payload = await parseJsonResponse(response) as { productHomeUrl?: string };
  return { productHomeUrl: payload.productHomeUrl || "http://localhost:3000/" };
}

export async function generateDiagram(form: FormData, onAccepted?: (pending: PendingTurn) => void): Promise<DiagramResult> {
  form.set("requestId", String(form.get("requestId") || createId()));
  return submitAndPoll<DiagramResult>("generate", "api/generate", form, onAccepted);
}

export async function sendChatMessage(sessionId: string, form: FormData, onAccepted?: (pending: PendingTurn) => void): Promise<ChatResult> {
  form.set("sessionId", sessionId);
  return submitAndPoll<ChatResult>("chat", "api/chat", form, onAccepted);
}

async function submitAndPoll<T>(kind: PendingTurn["kind"], url: string, body: FormData, onAccepted?: (pending: PendingTurn) => void): Promise<T> {
  while (true) {
    const response = await fetch(url, { method: "POST", body });
    const payload = await parseJsonResponse(response) as { ok?: boolean; error?: ApiError; result?: T } & Partial<Accepted>;
    if (response.status === 202 && payload.status === "processing" && payload.sessionId && payload.requestId) {
      const pending = { kind, sessionId: payload.sessionId, requestId: payload.requestId };
      onAccepted?.(pending);
      return pollTurn<T>(pending, async () => {
        const retry = await fetch(url, { method: "POST", body });
        const retryPayload = await parseJsonResponse(retry) as { ok?: boolean; error?: ApiError; result?: T } & Partial<Accepted>;
        if (retry.status === 202) return;
        if (retry.ok && retryPayload.ok !== false) return (retryPayload.ok ? retryPayload.result : retryPayload) as T;
        if (retry.status === 409 && retryPayload.error?.code === "request-in-progress") return;
        throw retryPayload.error;
      });
    }
    if (!response.ok || payload.ok === false) throw payload.error;
    return (payload.ok ? payload.result : payload) as T;
  }
}

export async function pollTurn<T>(pending: PendingTurn, retry?: () => Promise<T | undefined>): Promise<T> {
  const path = `api/${pending.kind}/${encodeURIComponent(pending.sessionId)}/turns/${encodeURIComponent(pending.requestId)}`;
  while (true) {
    let response: Response;
    try {
      response = await fetch(path);
    } catch {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      continue;
    }
    if ([502, 503, 504].includes(response.status)) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      continue;
    }
    const payload = await parseJsonResponse(response) as { ok?: boolean; result?: T; error?: ApiError; status?: string; retryable?: boolean };
    if (!response.ok) throw payload.error;
    if (payload.ok) return payload.result as T;
    if (payload.ok === false) throw payload.error;
    if (payload && typeof payload === "object" && "sessionId" in payload) return payload as T;
    if (payload.status === "failed" && payload.retryable) {
      if (!retry) throw { code: "diagram-generation", message: "Задача прервалась. Повторите запрос." } as ApiError;
      const result = await retry();
      if (result !== undefined) return result;
    } else if (payload.status !== "processing") {
      throw { code: "network-error", message: "Сервер вернул неизвестное состояние" } as ApiError;
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
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
