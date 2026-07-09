import mammoth from "mammoth";

/**
 * Extracts plain text from a DOCX buffer using mammoth's raw text extraction.
 * Never throws: any failure (malformed DOCX, unsupported format, parser error)
 * results in an empty string so callers can safely fall back.
 */
export async function parseDocx(buffer: Buffer): Promise<string> {
  try {
    const result = await mammoth.extractRawText({ buffer });
    return result.value.trim().slice(0, 60_000);
  } catch {
    return "";
  }
}
