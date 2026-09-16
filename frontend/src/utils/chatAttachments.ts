// Kept in sync by hand with backend-py's is_chat_document_format
// (backend-py/app/services/files/extract.py) -- .xls is deliberately excluded
// on both sides: it's the legacy OLE2/BIFF format, which the backend's
// openpyxl-based parser cannot read, so accepting it here would let the user
// attach a file whose content silently never reaches the model.
export const CHAT_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024;
export const CHAT_ATTACHMENT_FORMATS = ["txt", "docx", "pdf", "xlsx", "csv"] as const;
export const CHAT_ATTACHMENT_MIME_TYPES = new Set([
  "text/plain",
  "text/csv",
  "application/csv",
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
]);
export const CHAT_ATTACHMENT_ACCEPT = CHAT_ATTACHMENT_FORMATS.map((format) => `.${format}`).join(",");

export function extensionOf(name: string): string {
  return name.toLowerCase().split(".").pop() || "";
}

export function isAllowedChatAttachmentExtension(extension: string): boolean {
  return CHAT_ATTACHMENT_FORMATS.includes(extension as typeof CHAT_ATTACHMENT_FORMATS[number]);
}

export function isSameFile(left: File, right: File): boolean {
  return left.name === right.name && left.size === right.size && left.lastModified === right.lastModified;
}

export function validateChatFile(file: File, existingFiles: File[]): string {
  if (file.size > CHAT_ATTACHMENT_MAX_BYTES) return `Размер файла не должен превышать ${CHAT_ATTACHMENT_MAX_BYTES / (1024 * 1024)} МБ`;

  const extension = extensionOf(file.name);
  if (!isAllowedChatAttachmentExtension(extension)) return "Этот формат файла не поддерживается";
  if (file.type && !CHAT_ATTACHMENT_MIME_TYPES.has(file.type)) return "Этот формат файла не поддерживается";
  if (existingFiles.some((item) => isSameFile(item, file))) return "Файл уже добавлен";
  return "";
}
