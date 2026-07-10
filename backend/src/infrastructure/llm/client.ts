import { Agent } from "undici";
import { LLMError } from "./errors.ts";
import type { LLMErrorCode } from "./errors.ts";
export type { LLMErrorCode };

// Node's global fetch() runs on undici, which manages its own TLS context and
// does NOT read NODE_TLS_REJECT_UNAUTHORIZED (that only affects the legacy
// tls/https core modules). To trust a self-signed/internal-CA endpoint we
// have to hand fetch() an explicit insecure dispatcher instead.
const insecureDispatcher = new Agent({ connect: { rejectUnauthorized: false } });

export type ResponseFormatMode = "json_schema" | "json_object" | "none";

// ─── Pure helpers (exported for tests) ───────────────────────────────────────

// Preserves object identity for unchanged subtrees (returns `obj` itself when nothing
// changed) rather than always rebuilding. Required so that resolving a `$ref` to a leaf
// definition returns the same object reference as the definition — callers/tests rely on
// this for reference-equality checks, and it avoids unnecessary allocation for large schemas.
export function _inlineRefs(obj: unknown, defs: Record<string, unknown>): unknown {
  if (Array.isArray(obj)) {
    const mapped = obj.map((item) => _inlineRefs(item, defs));
    const changed = mapped.some((v, i) => v !== obj[i]);
    return changed ? mapped : obj;
  }
  if (obj !== null && typeof obj === "object") {
    const record = obj as Record<string, unknown>;
    if ("$ref" in record) {
      const name = (record["$ref"] as string).split("/").at(-1)!;
      return _inlineRefs(defs[name], defs);
    }
    let changed = false;
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(record)) {
      if (k === "$defs") {
        changed = true;
        continue;
      }
      const nv = _inlineRefs(v, defs);
      if (nv !== v) changed = true;
      result[k] = nv;
    }
    return changed ? result : obj;
  }
  return obj;
}

export function _stripThinkTags(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
}

export function _extractMermaid(raw: string): string {
  const cleaned = raw
    .replace(/```mermaid\s*/g, "")
    .replace(/```\s*/g, "")
    .trim();
  const start = cleaned.search(/flowchart\s+(LR|TB)/);
  if (start === -1) {
    throw new LLMError("EMPTY_RESPONSE", `No flowchart found: ${raw.slice(0, 200)}`);
  }
  return cleaned.slice(start).trim();
}

export function _extractJson(raw: string): Record<string, unknown> {
  const cleaned = raw.replace(/```json\s*/g, "").replace(/```\s*/g, "").trim();
  const start = cleaned.indexOf("{");
  if (start === -1) {
    throw new LLMError("INVALID_JSON", `No JSON object found: ${cleaned.slice(0, 200)}`);
  }
  // Try simple parse first (no trailing text)
  try {
    return JSON.parse(cleaned.slice(start)) as Record<string, unknown>;
  } catch {
    // Scan for matching closing brace (string-aware)
    let depth = 0;
    let inStr = false;
    let esc = false;
    let end = -1;
    for (let i = start; i < cleaned.length; i++) {
      const ch = cleaned[i];
      if (esc) { esc = false; continue; }
      if (inStr) { if (ch === "\\") esc = true; else if (ch === '"') inStr = false; continue; }
      if (ch === '"') { inStr = true; continue; }
      if (ch === "{") depth++;
      else if (ch === "}") { if (--depth === 0) { end = i; break; } }
    }
    if (end === -1) throw new LLMError("INVALID_JSON", `Unbalanced braces in: ${cleaned.slice(start, start + 200)}`);
    return JSON.parse(cleaned.slice(start, end + 1)) as Record<string, unknown>;
  }
}

// ─── VLLMClient (HTTP part added in Task 3) ──────────────────────────────────

export interface VLLMClientOptions {
  url: string;
  model: string;
  apiKey?: string;
  timeoutMs?: number;
  temperature?: number;
  seed?: number;
  responseFormatMode?: ResponseFormatMode;
  insecureTls?: boolean;
}

export class VLLMClient {
  readonly model: string;
  readonly timeoutMs: number;
  readonly temperature: number;
  readonly seed?: number;
  responseFormatMode: ResponseFormatMode;
  protected readonly baseUrl: string;
  protected readonly headers: Record<string, string>;
  protected readonly dispatcher: Agent | undefined;

  constructor(opts: VLLMClientOptions) {
    this.baseUrl = opts.url.replace(/\/chat\/completions$/, "").replace(/\/$/, "");
    this.model = opts.model;
    this.timeoutMs = opts.timeoutMs ?? 120_000;
    this.temperature = opts.temperature ?? 0.1;
    this.seed = opts.seed;
    this.responseFormatMode = opts.responseFormatMode ?? "json_schema";
    this.headers = { "Content-Type": "application/json" };
    if (opts.apiKey) this.headers["Authorization"] = `Bearer ${opts.apiKey}`;
    this.dispatcher = opts.insecureTls ? insecureDispatcher : undefined;
  }

  get endpoint(): string {
    return `${this.baseUrl}/chat/completions`;
  }

  private async _post(
    messages: { role: string; content: string }[],
    responseFormat?: unknown,
  ): Promise<{ content: string; reasoningContent: string }> {
    const payload: Record<string, unknown> = {
      model: this.model,
      messages,
      temperature: this.temperature,
      stream: false,
    };
    if (this.seed !== undefined) payload["seed"] = this.seed;
    if (responseFormat) payload["response_format"] = responseFormat;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      // `dispatcher` is an undici extension not present in the standard
      // RequestInit type, so the options object needs a loose cast.
      const requestInit = {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(payload),
        signal: controller.signal,
        dispatcher: this.dispatcher,
      } as RequestInit;

      const response = await fetch(this.endpoint, requestInit);

      if (!response.ok) {
        const body = await response.text().catch(() => "");
        if (response.status === 422 && this.responseFormatMode !== "none") {
          throw new LLMError(
            "STRUCTURED_OUTPUT_UNSUPPORTED",
            `Model rejected response_format: ${body.slice(0, 400)}`,
          );
        }
        throw new LLMError("HTTP_ERROR", `LLM HTTP ${response.status}: ${body.slice(0, 400)}`);
      }

      const data = await response.json() as {
        choices: { message: { content?: string; reasoning_content?: string } }[];
      };
      const msg = data.choices[0]?.message ?? {};
      return {
        content: msg.content ?? "",
        reasoningContent: (msg as Record<string, string>).reasoning_content ?? "",
      };
    } catch (err) {
      if (err instanceof LLMError) throw err;
      if ((err as Error).name === "AbortError") {
        throw new LLMError("TIMEOUT", `LLM timed out after ${this.timeoutMs}ms`);
      }
      throw new LLMError("NETWORK_ERROR", `LLM network error: ${err}`, err);
    } finally {
      clearTimeout(timer);
    }
  }

  async completeText(prompt: string, system?: string): Promise<string> {
    const messages: { role: string; content: string }[] = [];
    if (system) messages.push({ role: "system", content: system });
    messages.push({ role: "user", content: prompt });
    const { content } = await this._post(messages);
    return _extractMermaid(_stripThinkTags(content));
  }

  async completeJson(
    prompt: string,
    schema: Record<string, unknown>,
    schemaName: string,
    system?: string,
  ): Promise<Record<string, unknown>> {
    const messages: { role: string; content: string }[] = [];
    if (system) messages.push({ role: "system", content: system });
    messages.push({ role: "user", content: prompt });

    const defs = (schema["$defs"] as Record<string, unknown>) ?? {};
    const flatSchema = _inlineRefs(schema, defs) as Record<string, unknown>;

    let responseFormat: unknown;
    if (this.responseFormatMode === "json_schema") {
      responseFormat = {
        type: "json_schema",
        json_schema: { name: schemaName, strict: false, schema: flatSchema },
      };
    } else if (this.responseFormatMode === "json_object") {
      responseFormat = { type: "json_object" };
    }

    const { content, reasoningContent } = await this._post(messages, responseFormat);
    const raw = content.includes("{") ? content : (reasoningContent.includes("{") ? reasoningContent : content);
    return _extractJson(_stripThinkTags(raw));
  }
}
