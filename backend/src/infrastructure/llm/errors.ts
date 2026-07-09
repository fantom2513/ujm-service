export type LLMErrorCode =
  | "TIMEOUT"
  | "HTTP_ERROR"
  | "NETWORK_ERROR"
  | "INVALID_JSON"
  | "SCHEMA_MISMATCH"
  | "STRUCTURED_OUTPUT_UNSUPPORTED"
  | "EMPTY_RESPONSE";

export class LLMError extends Error {
  readonly code: LLMErrorCode;

  constructor(code: LLMErrorCode, message: string, cause?: unknown) {
    super(message, { cause });
    this.code = code;
    this.name = "LLMError";
  }
}
