import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CHAT_ATTACHMENT_FORMATS,
  CHAT_ATTACHMENT_MAX_BYTES,
  extensionOf,
  isAllowedChatAttachmentExtension,
  validateChatFile
} from "../../src/utils/chatAttachments.ts";

test("extensionOf lowercases and returns the part after the last dot", () => {
  assert.equal(extensionOf("Report.DOCX"), "docx");
  assert.equal(extensionOf("noextension"), "noextension");
});

test(".xls is not an allowed chat attachment format", () => {
  assert.equal(isAllowedChatAttachmentExtension("xls"), false);
  assert.equal(CHAT_ATTACHMENT_FORMATS.includes("xls" as never), false);
});

test(".xlsx and .csv remain allowed chat attachment formats", () => {
  assert.equal(isAllowedChatAttachmentExtension("xlsx"), true);
  assert.equal(isAllowedChatAttachmentExtension("csv"), true);
});

test("validateChatFile rejects .xls with the same unsupported-format message as an unknown extension", () => {
  const xlsFile = new File(["data"], "table.xls", { type: "application/vnd.ms-excel" });
  const unknownFile = new File(["data"], "table.unknown", { type: "" });

  assert.equal(validateChatFile(xlsFile, []), "Этот формат файла не поддерживается");
  assert.equal(validateChatFile(xlsFile, []), validateChatFile(unknownFile, []));
});

test("validateChatFile accepts a file up to the 20 MB limit", () => {
  const file = new File([new Uint8Array(CHAT_ATTACHMENT_MAX_BYTES)], "spec.txt", { type: "text/plain" });

  assert.equal(validateChatFile(file, []), "");
});

test("validateChatFile rejects a file over the 20 MB limit", () => {
  const file = new File([new Uint8Array(CHAT_ATTACHMENT_MAX_BYTES + 1)], "spec.txt", { type: "text/plain" });

  assert.equal(validateChatFile(file, []), "Размер файла не должен превышать 20 МБ");
});

test("validateChatFile rejects a file already attached", () => {
  const existing = new File(["data"], "spec.txt", { type: "text/plain", lastModified: 1000 });

  assert.equal(validateChatFile(existing, [existing]), "Файл уже добавлен");
});
