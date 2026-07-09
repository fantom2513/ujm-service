import { LLMError } from "./errors.ts";
import type { LLMErrorCode, ResponseFormatMode, VLLMClient } from "./client.ts";

const NO_RETRY_CODES = new Set<LLMErrorCode>([
  "SCHEMA_MISMATCH",
  "STRUCTURED_OUTPUT_UNSUPPORTED",
  "INVALID_JSON",
  "EMPTY_RESPONSE",
]);

const FALLBACK_CODES = new Set<LLMErrorCode>([
  "SCHEMA_MISMATCH",
  "STRUCTURED_OUTPUT_UNSUPPORTED",
  "INVALID_JSON",
]);

const FALLBACK_CHAIN: ResponseFormatMode[] = ["json_schema", "json_object", "none"];

export async function executeWithRetry<T>(
  fn: () => Promise<T>,
  maxAttempts = 3,
  baseDelayMs = 1_000,
  maxDelayMs = 30_000,
): Promise<T> {
  let lastErr: LLMError | undefined;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (!(err instanceof LLMError)) throw err;
      if (NO_RETRY_CODES.has(err.code)) throw err;
      lastErr = err;
      if (attempt < maxAttempts - 1) {
        const delay = Math.min(baseDelayMs * 2 ** attempt, maxDelayMs);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }
  throw lastErr!;
}

export async function completeJsonWithFallback<T>(
  makeClient: (mode: ResponseFormatMode) => VLLMClient,
  startMode: ResponseFormatMode,
  call: (client: VLLMClient) => Promise<T>,
  maxAttemptsFirst = 3,
  maxAttemptsRest = 2,
): Promise<T> {
  const startIndex = Math.max(0, FALLBACK_CHAIN.indexOf(startMode));
  let lastErr: LLMError | undefined;

  for (let i = startIndex; i < FALLBACK_CHAIN.length; i++) {
    const mode = FALLBACK_CHAIN[i];
    const client = makeClient(mode);
    try {
      return await executeWithRetry(
        () => call(client),
        i === startIndex ? maxAttemptsFirst : maxAttemptsRest,
      );
    } catch (err) {
      if (!(err instanceof LLMError)) throw err;
      lastErr = err;
      if (FALLBACK_CODES.has(err.code) && i < FALLBACK_CHAIN.length - 1) continue;
      throw err;
    }
  }
  throw lastErr ?? new LLMError("SCHEMA_MISMATCH", "All response_format modes exhausted");
}
