import { test } from "node:test";
import assert from "node:assert/strict";
import { parseMultipart } from "../../src/server/multipart.ts";

function buildMultipartBuffer(boundary: string, filename: string, fileContent: string, extraField?: { name: string; value: string }): Buffer {
  const parts: Buffer[] = [];
  if (extraField) {
    parts.push(Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="${extraField.name}"\r\n\r\n${extraField.value}\r\n`,
      "utf8"
    ));
  }
  parts.push(Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: text/plain\r\n\r\n`,
    "utf8"
  ));
  parts.push(Buffer.from(fileContent, "utf8"));
  parts.push(Buffer.from(`\r\n--${boundary}--\r\n`, "utf8"));
  return Buffer.concat(parts);
}

test("parseMultipart: decodes a Cyrillic filename correctly", () => {
  const boundary = "testboundary123";
  const cyrillicFilename = "Утвержденное ТЗ.docx";
  const buffer = buildMultipartBuffer(boundary, cyrillicFilename, "hello world");
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.files.length, 1);
  assert.equal(result.files[0].filename, cyrillicFilename);
});

test("parseMultipart: still decodes plain ASCII filenames correctly", () => {
  const boundary = "testboundary456";
  const buffer = buildMultipartBuffer(boundary, "report.docx", "hello world");
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.files[0].filename, "report.docx");
});

test("parseMultipart: still decodes UTF-8 field values correctly (regression guard)", () => {
  const boundary = "testboundary789";
  const buffer = buildMultipartBuffer(boundary, "report.docx", "hello world", { name: "details", value: "Проверка полей" });
  const result = parseMultipart(buffer, `multipart/form-data; boundary=${boundary}`);

  assert.equal(result.fields.details, "Проверка полей");
});
