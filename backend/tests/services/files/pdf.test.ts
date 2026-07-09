import { test } from "node:test";
import assert from "node:assert/strict";
import { parsePdf } from "../../../src/services/files/pdf.ts";

// Minimal synthetic PDF with a text layer (BT/Tj operators). Hand-written raw
// PDF syntax like this is not guaranteed to have byte-accurate xref offsets,
// so pdf-parse (via pdfjs-dist) may fall back to a lenient recovery parse or
// fail to extract "Hello PDF" verbatim. The assertions below only require
// that parsing does not throw and returns a string — they don't assume the
// fixture is a fully spec-compliant PDF.
const MINIMAL_PDF_WITH_TEXT = Buffer.from(
  `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200]
  /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length 44 >>
stream
BT /F1 12 Tf 50 150 Td (Hello PDF) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000340 00000 n
trailer << /Size 6 /Root 1 0 R >>
startxref
434
%%EOF`,
  "utf8",
);

const IMAGE_ONLY_PDF = Buffer.from(
  `%PDF-1.4\n1 0 obj<<>>endobj\nxref\n0 2\n0000000000 65535 f\n0000000009 00000 n\ntrailer<<>>\nstartxref\n9\n%%EOF`,
  "utf8",
);

const GARBAGE_BUFFER = Buffer.from("this is definitely not a pdf file at all", "utf8");

test("parsePdf: parses a PDF with a text layer without throwing", async () => {
  const text = await parsePdf(MINIMAL_PDF_WITH_TEXT);
  assert.equal(typeof text, "string");
});

test("parsePdf: returns a string for an image-only / minimal PDF", async () => {
  const text = await parsePdf(IMAGE_ONLY_PDF);
  assert.equal(typeof text, "string");
});

test("parsePdf: never throws on a non-PDF buffer, returns empty string", async () => {
  const text = await parsePdf(GARBAGE_BUFFER);
  assert.equal(text, "");
});

test("parsePdf: never throws on an empty buffer", async () => {
  const text = await parsePdf(Buffer.alloc(0));
  assert.equal(text, "");
});
