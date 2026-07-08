import type { SourceType, UserErrorCode } from "../../../shared/types/index.ts";

export interface UploadedFile {
  fieldName: string;
  filename: string;
  contentType: string;
  size: number;
  buffer: Buffer;
}

export interface MultipartBody {
  fields: Record<string, string>;
  files: UploadedFile[];
}

export interface ApiErrorPayload {
  code: UserErrorCode;
  message: string;
  field?: string;
}

export interface AppConfig {
  host: string;
  port: number;
  productHomeUrl: string;
  maxTextFileBytes: number;
  maxRecordingFileBytes: number;
  maxChatAttachmentBytes: number;
  requestTimeoutMs: number;
}

export interface NormalizedSource {
  type: SourceType;
  title: string;
  text: string;
  description: string;
  file?: {
    name: string;
    format: string;
    size: number;
  };
  url?: string;
  stub?: boolean;
}
