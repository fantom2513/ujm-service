import { PDFParse } from "pdf-parse";

/**
 * Extracts plain text from a PDF buffer.
 *
 * Uses pdf-parse v2's class-based API (`PDFParse`/`getText`), which is a
 * ground-up rewrite of the legacy 1.x `pdf-parse(buffer)` function API.
 * Never throws: any failure (malformed PDF, image-only PDF, parser error)
 * results in an empty string so callers can safely fall back.
 */
export async function parsePdf(buffer: Buffer): Promise<string> {
  let parser: PDFParse | undefined;
  try {
    parser = new PDFParse({ data: buffer });
    const result = await parser.getText();
    return result.text.trim().slice(0, 60_000);
  } catch {
    return "";
  } finally {
    if (parser) {
      try {
        await parser.destroy();
      } catch {
        // ignore cleanup errors
      }
    }
  }
}
