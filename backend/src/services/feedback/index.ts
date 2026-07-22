export interface FeedbackEntry {
  messageId: string;
  kind: "rating" | "copy";
  value?: "up" | "down";
  timestamp: string;
}

export function parseFeedbackEntry(fields: Record<string, string>): FeedbackEntry | null {
  const messageId = fields.messageId;
  const kind = fields.kind;
  const value = fields.value;

  if (!messageId || (kind !== "rating" && kind !== "copy")) return null;
  if (kind === "rating" && value !== "up" && value !== "down") return null;

  return {
    messageId,
    kind,
    value: kind === "rating" ? (value as "up" | "down") : undefined,
    timestamp: new Date().toISOString()
  };
}

export function recordFeedback(entry: FeedbackEntry): void {
  console.log("[feedback]", JSON.stringify(entry));
}
