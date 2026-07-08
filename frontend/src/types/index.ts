import type { ChatMessage, DiagramResult, FileMeta, SourceType, UserErrorCode } from "../../../shared/types/index.ts";

export type Page = "start" | "result";

export interface DiagramViewState {
  scale: number;
  x: number;
  y: number;
}

export interface StartState {
  sourceType: SourceType;
  link: string;
  details: string;
  file?: FileMeta;
  recording?: FileMeta;
  error?: {
    code: UserErrorCode;
    message: string;
    field?: string;
  };
}

export interface AppState {
  page: Page;
  start: StartState;
  result?: DiagramResult;
  view: DiagramViewState;
  chatDraft: string;
  chatAttachment?: FileMeta;
  chatAttachments?: FileMeta[];
  config: {
    productHomeUrl: string;
  };
}

export interface ApiError {
  code: UserErrorCode;
  message: string;
  field?: string;
}
