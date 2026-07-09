import { LLMError } from "./errors.ts";
import type { LLMErrorCode } from "./errors.ts";
export type { LLMErrorCode };

export type ResponseFormatMode = "json_schema" | "json_object" | "none";

// ─── Pure helpers (exported for tests) ───────────────────────────────────────

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
}

export class VLLMClient {
  readonly model: string;
  readonly timeoutMs: number;
  readonly temperature: number;
  readonly seed?: number;
  responseFormatMode: ResponseFormatMode;
  protected readonly baseUrl: string;
  protected readonly headers: Record<string, string>;

  constructor(opts: VLLMClientOptions) {
    this.baseUrl = opts.url.replace(/\/chat\/completions$/, "").replace(/\/$/, "");
    this.model = opts.model;
    this.timeoutMs = opts.timeoutMs ?? 120_000;
    this.temperature = opts.temperature ?? 0.1;
    this.seed = opts.seed;
    this.responseFormatMode = opts.responseFormatMode ?? "json_schema";
    this.headers = { "Content-Type": "application/json" };
    if (opts.apiKey) this.headers["Authorization"] = `Bearer ${opts.apiKey}`;
  }

  get endpoint(): string {
    return `${this.baseUrl}/chat/completions`;
  }

  // completeText and completeJson added in Task 3
}
