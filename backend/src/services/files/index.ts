import type { UploadedFile, NormalizedSource } from "../../types/index.ts";

const textFormats = new Set(["txt", "docx", "pdf"]);
const tableFormats = new Set(["xls", "xlsx", "csv"]);

export function getExtension(filename: string): string {
  const parts = filename.toLowerCase().split(".");
  return parts.length > 1 ? parts.at(-1) || "" : "";
}

export function sanitizeFilename(filename: string): string {
  return filename.replace(/[\\/:*?"<>|]/g, "_").slice(0, 140) || "file";
}

export function isTextSourceFormat(format: string): boolean {
  return textFormats.has(format);
}

export function isChatDocumentFormat(format: string): boolean {
  return textFormats.has(format) || tableFormats.has(format);
}

export function hasPdfTextLayer(file: UploadedFile): boolean {
  if (getExtension(file.filename) !== "pdf") return true;
  const content = file.buffer.toString("latin1");
  return /\bBT\b/.test(content) && /(Tj|TJ)\b/.test(content);
}

export function normalizeTextFile(file: UploadedFile): NormalizedSource {
  const format = getExtension(file.filename);
  const safeName = sanitizeFilename(file.filename);
  let text = `Файл ${safeName} принят каркасом backend.`;

  if (format === "txt" || format === "csv") {
    text = file.buffer.toString("utf8").slice(0, 12000);
  }

  if (format === "docx" || format === "pdf" || format === "xls" || format === "xlsx") {
    text = `Извлечение содержимого ${format.toUpperCase()} будет подключено в сервисе files. Сейчас используется тестовый контекст каркаса.`;
  }

  return {
    type: "text-file",
    title: safeName,
    text,
    description: `${format.toUpperCase()} · ${Math.round(file.size / 1024)} КБ`,
    file: {
      name: safeName,
      format: format.toUpperCase(),
      size: file.size
    },
    stub: format !== "txt" && format !== "csv"
  };
}
