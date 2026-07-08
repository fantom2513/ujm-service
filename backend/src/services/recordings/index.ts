import type { UploadedFile, NormalizedSource } from "../../types/index.ts";
import { getExtension, sanitizeFilename } from "../files/index.ts";

const recordingFormats = new Set(["mp3", "m4a", "mp4", "webm"]);

export function isRecordingFormat(format: string): boolean {
  return recordingFormats.has(format);
}

export function normalizeRecording(file: UploadedFile): NormalizedSource {
  const format = getExtension(file.filename);
  const safeName = sanitizeFilename(file.filename);

  return {
    type: "recording",
    title: safeName,
    text: "Временная транскрибация записи. Реальное извлечение аудиодорожки и распознавание речи подключаются в сервисе recordings.",
    description: `${format.toUpperCase()} · ${Math.round(file.size / 1024)} КБ`,
    file: {
      name: safeName,
      format: format.toUpperCase(),
      size: file.size
    },
    stub: true
  };
}
