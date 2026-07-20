import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Loads the full, authored system prompts from backend/src/prompts/ (relative
// to this file, not process.cwd(), so it resolves correctly regardless of
// where the process was launched from).
function loadPrompt(filename: string): string {
  const path = fileURLToPath(new URL(`../../prompts/${filename}`, import.meta.url));
  return readFileSync(path, "utf8").trim();
}

const GENERATE_SYSTEM = loadPrompt("generateMermaid.prompt.txt");
const EDIT_SYSTEM = loadPrompt("editMermaid.prompt.txt");
const REPAIR_SYSTEM = loadPrompt("repairMermaid.prompt.txt");

function sanitize(text: string): string {
  return text.trim().slice(0, 60_000).replace(/```/g, "'''");
}

export function buildGeneratePrompt(sourceText: string, additionalDetails: string): string {
  const safeSource = sanitize(sourceText);
  const safeDetails = sanitize(additionalDetails);
  const detailsBlock = safeDetails
    ? `<ADDITIONAL_DETAILS>\n${safeDetails}\n</ADDITIONAL_DETAILS>`
    : `<ADDITIONAL_DETAILS></ADDITIONAL_DETAILS>`;

  return `${GENERATE_SYSTEM}\n\n<SOURCE_SPECIFICATION>\n${safeSource}\n</SOURCE_SPECIFICATION>\n\n${detailsBlock}`;
}

export interface HistoryEntry {
  role: "user" | "assistant";
  text: string;
}

export interface ChatPromptOptions {
  sourceText: string;
  additionalDetails: string;
  currentMermaid: string;
  previousMermaid: string | undefined;
  actionType: "FREEFORM" | "GROUP_SEMANTIC_BLOCKS" | "SIMPLIFY" | "HIGHLIGHT_MAIN_PATH" | "RESTORE_PREVIOUS";
  userMessage: string;
  attachmentContext: string;
  history: HistoryEntry[];
}

function formatHistory(history: HistoryEntry[]): string {
  return history
    .map((entry) => `${entry.role === "user" ? "Пользователь" : "Ассистент"}: ${sanitize(entry.text)}`)
    .join("\n");
}

export function buildChatPrompt(opts: ChatPromptOptions): string {
  const prevBlock = opts.previousMermaid
    ? `<PREVIOUS_MERMAID>\n${opts.previousMermaid}\n</PREVIOUS_MERMAID>`
    : `<PREVIOUS_MERMAID></PREVIOUS_MERMAID>`;

  const attachBlock = opts.attachmentContext
    ? `<ATTACHMENT_CONTEXT>\n${sanitize(opts.attachmentContext)}\n</ATTACHMENT_CONTEXT>`
    : `<ATTACHMENT_CONTEXT></ATTACHMENT_CONTEXT>`;

  const historyBlock = opts.history.length
    ? `<CHAT_HISTORY>\n${formatHistory(opts.history)}\n</CHAT_HISTORY>`
    : `<CHAT_HISTORY></CHAT_HISTORY>`;

  return `${EDIT_SYSTEM}

<SOURCE_SPECIFICATION>
${sanitize(opts.sourceText)}
</SOURCE_SPECIFICATION>

<ADDITIONAL_DETAILS>
${sanitize(opts.additionalDetails)}
</ADDITIONAL_DETAILS>

<CURRENT_MERMAID>
${opts.currentMermaid}
</CURRENT_MERMAID>

${prevBlock}

${historyBlock}

<ACTION_TYPE>
${opts.actionType}
</ACTION_TYPE>

<USER_MESSAGE>
${sanitize(opts.userMessage)}
</USER_MESSAGE>

${attachBlock}`;
}

export function buildRepairPrompt(
  candidateMermaid: string,
  parserError: string,
  validationIssues: string[],
): string {
  return `${REPAIR_SYSTEM}

<CANDIDATE_MERMAID>
${candidateMermaid}
</CANDIDATE_MERMAID>

<PARSER_ERROR>
${parserError}
</PARSER_ERROR>

<VALIDATION_ISSUES>
${validationIssues.join("\n")}
</VALIDATION_ISSUES>`;
}
