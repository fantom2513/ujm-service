import type { MultipartBody, UploadedFile } from "../types/index.ts";

export function parseMultipart(buffer: Buffer, contentType: string): MultipartBody {
  const boundaryMatch = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType);
  if (!boundaryMatch) return { fields: {}, files: [] };
  const boundary = boundaryMatch[1] || boundaryMatch[2];
  const raw = buffer.toString("latin1");
  const parts = raw.split(`--${boundary}`).slice(1, -1);
  const fields: Record<string, string> = {};
  const files: UploadedFile[] = [];

  for (const part of parts) {
    const normalizedPart = part.replace(/^\r\n/, "").replace(/\r\n$/, "");
    const headerEnd = normalizedPart.indexOf("\r\n\r\n");
    if (headerEnd === -1) continue;

    const headerText = normalizedPart.slice(0, headerEnd);
    const bodyText = normalizedPart.slice(headerEnd + 4);
    const disposition = /content-disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="([^"]*)")?/i.exec(headerText);
    if (!disposition) continue;

    const fieldName = disposition[1];
    const filename = disposition[2] ? Buffer.from(disposition[2], "latin1").toString("utf8") : undefined;
    const typeMatch = /content-type:\s*([^\r\n]+)/i.exec(headerText);
    const contentTypeHeader = typeMatch?.[1]?.trim() || "application/octet-stream";

    if (filename) {
      const bodyBuffer = Buffer.from(bodyText, "latin1");
      files.push({
        fieldName,
        filename,
        contentType: contentTypeHeader,
        size: bodyBuffer.length,
        buffer: bodyBuffer
      });
    } else {
      fields[fieldName] = Buffer.from(bodyText, "latin1").toString("utf8");
    }
  }

  return { fields, files };
}
