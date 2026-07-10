import { VLLMClient } from "../../infrastructure/llm/client.ts";
import { completeJsonWithFallback, executeWithRetry } from "../../infrastructure/llm/retry.ts";
import { LLMError } from "../../infrastructure/llm/errors.ts";
import { buildChatPrompt, buildGeneratePrompt, buildRepairPrompt, type ChatPromptOptions } from "./prompts.ts";
import { validateMermaid } from "../mermaid/index.ts";
import { config } from "../../config/index.ts";
import type { NormalizedSource } from "../../types/index.ts";

export function makeClient(): VLLMClient {
  return new VLLMClient({
    url: config.llmUrl,
    model: config.llmModel,
    apiKey: config.llmApiKey,
    timeoutMs: config.llmTimeoutMs,
    temperature: config.llmTemperature,
    seed: config.llmSeed,
    responseFormatMode: config.llmResponseFormatMode,
    insecureTls: config.llmInsecureTls
  });
}

export async function generateDiagram(
  src: NormalizedSource,
  details: string,
  client: VLLMClient = makeClient()
): Promise<string> {
  const prompt = buildGeneratePrompt(src.text, details);
  return executeWithRetry(() => client.completeText(prompt));
}

const CHAT_OUTPUT_SCHEMA = {
  type: "object",
  properties: {
    mermaid: { type: "string" },
    message: { type: "string" }
  },
  required: ["mermaid", "message"],
  additionalProperties: false
};

export interface ChatEditResult {
  mermaidCode: string;
  message: string;
}

export async function chatEdit(opts: ChatPromptOptions): Promise<ChatEditResult> {
  const prompt = buildChatPrompt(opts);

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
    (client) => client.completeJson(prompt, CHAT_OUTPUT_SCHEMA, "ChatOutput")
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

  return { mermaidCode, message };
}
