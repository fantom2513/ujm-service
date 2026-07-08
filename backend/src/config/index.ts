import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { AppConfig } from "../types/index.ts";

function loadEnvFile(): void {
  const envPath = join(process.cwd(), ".env");
  if (!existsSync(envPath)) return;

  const lines = readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const index = trimmed.indexOf("=");
    if (index === -1) continue;
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim();
    if (!process.env[key]) process.env[key] = value;
  }
}

function megabytes(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed * 1024 * 1024 : fallback * 1024 * 1024;
}

loadEnvFile();

export const config: AppConfig = {
  host: process.env.APP_HOST || "127.0.0.1",
  port: Number(process.env.APP_PORT || "4173"),
  productHomeUrl: process.env.PRODUCT_HOME_URL || "http://localhost:3000/",
  maxTextFileBytes: megabytes(process.env.MAX_TEXT_FILE_MB, 10),
  maxRecordingFileBytes: megabytes(process.env.MAX_RECORDING_FILE_MB, 100),
  maxChatAttachmentBytes: megabytes(process.env.MAX_CHAT_ATTACHMENT_MB, 10),
  requestTimeoutMs: Number(process.env.REQUEST_TIMEOUT_MS || "120000")
};
