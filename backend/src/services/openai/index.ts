import type { NormalizedSource } from "../../types/index.ts";
import { TEST_MERMAID } from "../mermaid/index.ts";

export function generateDiagramStub(source: NormalizedSource, details: string): string {
  void source;
  void details;
  // Temporary stub: real OpenAI generation will be connected only after model,
  // prompt storage and API key configuration are approved.
  return TEST_MERMAID;
}

export function chatEditStub(): string {
  return "Временная заглушка: AI-редактирование пока не подключено, схема оставлена без изменений.";
}
