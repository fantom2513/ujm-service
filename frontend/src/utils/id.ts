type CryptoSource = {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
};

/**
 * Generates request/message identifiers in browsers where randomUUID is not
 * exposed. This happens on older browsers and when an internal test site is
 * not considered a secure context because its TLS certificate is invalid.
 */
export function createId(source: CryptoSource | undefined = globalThis.crypto as CryptoSource | undefined): string {
  if (typeof source?.randomUUID === "function") {
    return source.randomUUID();
  }

  if (typeof source?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    source.getRandomValues(bytes);
    // RFC 4122 version 4 / variant 1 bits.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }

  // Request IDs are idempotency keys, not credentials. This final fallback is
  // only for environments without Web Crypto and combines time with entropy.
  return `fallback-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
