import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { config } from "../config/index.ts";
import type { ApiErrorPayload, MultipartBody, UploadedFile } from "../types/index.ts";
import { getExtension, hasPdfTextLayer, isTextSourceFormat, normalizeTextFile } from "../services/files/index.ts";
import { isRecordingFormat, normalizeRecording } from "../services/recordings/index.ts";
import { classifyWorkLink, normalizeLink } from "../services/links/index.ts";
import { generateDiagram, chatEditStub } from "../services/openai/index.ts";
import { validateMermaid } from "../services/mermaid/index.ts";
import { normalizeChatAttachment } from "../services/chatAttachments/index.ts";

const distRoot = join(process.cwd(), "frontend", "dist");

const userMessages: Record<string, string> = {
  "file-required": "Необходимо прикрепить файл",
  "file-format": "Некорректный формат файла",
  "file-size-text": "Файл превышает 10 МБ",
  "file-size-recording": "Файл превышает 100 МБ",
  "link-required": "Поле обязательно для заполнения",
  "invalid-link": "Неверный формат ссылки",
  "source-unavailable": "Источник недоступен. Проверьте ссылку и права доступа",
  "diagram-generation": "Схема не сформирована. Перезагрузите страницу или повторите попытку позже",
  "attachment-error": "Ошибка загрузки файла"
};

function sendJson(response: ServerResponse, status: number, payload: unknown): void {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff"
  });
  response.end(JSON.stringify(payload));
}

function sendApiError(response: ServerResponse, status: number, error: ApiErrorPayload): void {
  sendJson(response, status, { ok: false, error });
}

function readRequest(request: IncomingMessage, maxBytes = config.maxRecordingFileBytes + 1024 * 1024): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    request.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(new Error("Request is too large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks)));
    request.on("error", reject);
  });
}

function parseMultipart(buffer: Buffer, contentType: string): MultipartBody {
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
    const filename = disposition[2];
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

async function readBody(request: IncomingMessage): Promise<MultipartBody> {
  const contentType = request.headers["content-type"] || "";
  const buffer = await readRequest(request);

  if (contentType.includes("multipart/form-data")) {
    return parseMultipart(buffer, contentType);
  }

  if (contentType.includes("application/json")) {
    const parsed = JSON.parse(buffer.toString("utf8") || "{}") as Record<string, string>;
    return { fields: parsed, files: [] };
  }

  return { fields: {}, files: [] };
}

function firstFile(body: MultipartBody): UploadedFile | undefined {
  return body.files[0];
}

async function handleGenerate(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = await readBody(request);
  const sourceType = body.fields.sourceType;
  const details = body.fields.details || "";
  let source;

  if (sourceType === "text-file") {
    const file = firstFile(body);
    if (!file || !file.filename) {
      return sendApiError(response, 400, { code: "file-required", message: userMessages["file-required"] });
    }

    const format = getExtension(file.filename);
    if (file.size > config.maxTextFileBytes) {
      return sendApiError(response, 400, { code: "file-size", message: userMessages["file-size-text"] });
    }
    if (!isTextSourceFormat(format)) {
      return sendApiError(response, 400, { code: "file-format", message: userMessages["file-format"] });
    }
    if (!hasPdfTextLayer(file)) {
      return sendApiError(response, 400, { code: "attachment-error", message: userMessages["attachment-error"], field: "attachment" });
    }

    source = await normalizeTextFile(file);
  } else if (sourceType === "recording") {
    const file = firstFile(body);
    if (!file || !file.filename) {
      return sendApiError(response, 400, { code: "file-required", message: userMessages["file-required"] });
    }

    const format = getExtension(file.filename);
    if (file.size > config.maxRecordingFileBytes) {
      return sendApiError(response, 400, { code: "file-size", message: userMessages["file-size-recording"] });
    }
    if (!isRecordingFormat(format)) {
      return sendApiError(response, 400, { code: "file-format", message: userMessages["file-format"] });
    }

    source = normalizeRecording(file);
  } else if (sourceType === "link") {
    const link = (body.fields.link || "").trim();
    if (!link) {
      return sendApiError(response, 400, { code: "link-required", message: userMessages["link-required"] });
    }
    if (!classifyWorkLink(link)) {
      return sendApiError(response, 400, { code: "invalid-link", message: userMessages["invalid-link"] });
    }
    source = normalizeLink(link);
  } else {
    return sendApiError(response, 400, { code: "diagram-generation", message: userMessages["diagram-generation"] });
  }

  let mermaidCode: string;
  try {
    mermaidCode = await generateDiagram(source, details);
  } catch {
    return sendApiError(response, 500, { code: "diagram-generation", message: userMessages["diagram-generation"] });
  }
  const validation = validateMermaid(mermaidCode);
  if (!validation.ok) {
    return sendApiError(response, 500, { code: "diagram-generation", message: userMessages["diagram-generation"] });
  }

  sendJson(response, 200, {
    ok: true,
    result: {
      title: "Тестовая User Flow-схема",
      mermaidCode,
      sourceText: source.text,
      sourceContext: {
        type: source.type,
        title: source.title,
        description: source.description,
        file: source.file,
        url: source.url,
        stub: source.stub
      },
      details,
      chat: [],
      warnings: source.stub ? ["Используется временная заглушка backend."] : []
    }
  });
}

async function handleChat(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = await readBody(request);
  const mermaidCode = body.fields.mermaidCode || "";
  const message = body.fields.message || "";
  const attachment = firstFile(body);
  let attachmentNote = "";

  if (attachment) {
    if (attachment.size > config.maxChatAttachmentBytes) {
      return sendApiError(response, 400, { code: "file-size", message: userMessages["file-size-text"], field: "attachment" });
    }
    const normalized = await normalizeChatAttachment(attachment);
    if (!normalized.ok) {
      return sendApiError(response, 400, {
        code: normalized.reason === "format" ? "file-format" : "attachment-error",
        message: normalized.reason === "format" ? userMessages["file-format"] : userMessages["attachment-error"],
        field: "attachment"
      });
    }
    attachmentNote = " Прикрепленный файл принят как дополнительный контекст, но пока не влияет на схему.";
  }

  const validation = validateMermaid(mermaidCode);
  const safeCode = validation.ok ? mermaidCode : "";
  sendJson(response, 200, {
    ok: true,
    result: {
      mermaidCode: safeCode,
      message: `${chatEditStub()}${attachmentNote}`,
      temporary: true,
      userMessage: message
    }
  });
}

async function handleStatic(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  const pathName = decodeURIComponent(url.pathname);
  const requestedPath = pathName === "/" ? "index.html" : pathName.replace(/^\//, "");
  const safePath = normalize(requestedPath).replace(/^(\.\.[/\\])+/, "");
  let filePath = join(distRoot, safePath);

  if (!existsSync(filePath)) {
    filePath = join(distRoot, "index.html");
  }

  try {
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) throw new Error("Not a file");
    const file = await readFile(filePath);
    response.writeHead(200, {
      "Content-Type": mimeType(filePath),
      "Cache-Control": filePath.endsWith("index.html") ? "no-store" : "public, max-age=3600",
      "X-Content-Type-Options": "nosniff"
    });
    response.end(file);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
}

function mimeType(filePath: string): string {
  const ext = extname(filePath);
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  if (ext === ".svg") return "image/svg+xml";
  return "application/octet-stream";
}

const server = createServer(async (request, response) => {
  try {
    if (request.url?.startsWith("/api/health") && request.method === "GET") {
      return sendJson(response, 200, { ok: true, service: "copilot-mermaid-skeleton" });
    }
    if (request.url?.startsWith("/api/config") && request.method === "GET") {
      return sendJson(response, 200, { ok: true, productHomeUrl: config.productHomeUrl });
    }
    if (request.url?.startsWith("/api/generate") && request.method === "POST") {
      return await handleGenerate(request, response);
    }
    if (request.url?.startsWith("/api/chat") && request.method === "POST") {
      return await handleChat(request, response);
    }
    return await handleStatic(request, response);
  } catch {
    return sendApiError(response, 500, { code: "diagram-generation", message: userMessages["diagram-generation"] });
  }
});

server.requestTimeout = config.requestTimeoutMs;
server.listen(config.port, config.host, () => {
  console.log(`Copilot Mermaid skeleton is running at http://${config.host}:${config.port}`);
});
