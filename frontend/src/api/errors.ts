import type { ApiError } from "../types/index.ts";

export type ApiErrorContext = "generate" | "chat";

const FALLBACKS: Record<ApiErrorContext, ApiError> = {
  generate: {
    code: "diagram-generation",
    message: "Схема не сформирована. Перезагрузите страницу или повторите попытку позже"
  },
  chat: {
    code: "chat-message-failed",
    message: "Не удалось отправить сообщение. Попробуйте ещё раз позже"
  }
};

function isValidApiError(error: unknown): error is ApiError {
  if (!error || typeof error !== "object") return false;
  const candidate = error as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

export function normalizeApiError(error: unknown, context: ApiErrorContext): ApiError {
  if (isValidApiError(error)) return error;
  return FALLBACKS[context];
}
