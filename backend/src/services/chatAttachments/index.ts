import type { UploadedFile } from "../../types/index.ts";
import { getExtension, hasPdfTextLayer, isChatDocumentFormat, normalizeTextFile } from "../files/index.ts";
import { isRecordingFormat, normalizeRecording } from "../recordings/index.ts";

export async function normalizeChatAttachment(file: UploadedFile): Promise<{ ok: true; text: string } | { ok: false; reason: "format" | "attachment" }> {
  const format = getExtension(file.filename);

  if (isChatDocumentFormat(format)) {
    if (!hasPdfTextLayer(file)) return { ok: false, reason: "attachment" };
    const normalized = await normalizeTextFile(file);
    return { ok: true, text: normalized.text };
  }

  if (isRecordingFormat(format)) {
    const normalized = normalizeRecording(file);
    return { ok: true, text: normalized.text };
  }

  return { ok: false, reason: "format" };
}
