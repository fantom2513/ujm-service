export type SourceType = "text-file" | "recording" | "link";

export type UserErrorCode =
  | "file-required"
  | "file-format"
  | "file-size"
  | "link-required"
  | "invalid-link"
  | "source-unavailable"
  | "diagram-generation"
  | "attachment-error"
  | "invalid-request"
  | "session-required"
  | "request-id-required"
  | "session-not-found"
  | "request-in-progress"
  | "request-id-conflict"
  | "version-conflict"
  | "chat-message-failed";

export interface FileMeta {
  name: string;
  format: string;
  size: number;
}

export interface SourceContext {
  type: SourceType;
  title: string;
  description: string;
  file?: FileMeta;
  url?: string;
  stub?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  attachment?: FileMeta;
  attachments?: FileMeta[];
  temporary?: boolean;
  feedback?: "up" | "down";
}

export interface DiagramResult {
  sessionId: string;
  title: string;
  mermaidCode: string;
  sourceText: string;
  sourceContext: SourceContext;
  details?: string;
  chat: ChatMessage[];
  warnings: string[];
}

export interface ChatResult {
  sessionId: string;
  mermaidCode: string;
  message: string;
}
