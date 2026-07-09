import { VLLMClient } from "../../infrastructure/llm/client.ts";
import { executeWithRetry } from "../../infrastructure/llm/retry.ts";
import { buildGeneratePrompt } from "./prompts.ts";
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
    responseFormatMode: config.llmResponseFormatMode
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

export function chatEditStub(): string {
  return "Временная заглушка: AI-редактирование пока не подключено, схема оставлена без изменений.";
}
