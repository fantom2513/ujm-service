export type RequiredSourceError = "file-required" | "link-required" | "diagram-generation";

export interface RequiredSourceInput {
  sourceType: string | undefined;
  hasFile: boolean;
  link: string;
}

/**
 * Guards against "silent generation" (#12): a /api/generate request that carries
 * no usable source must be rejected with a 400 before we ever call the LLM.
 *
 * Returns the error code to send back, or null when a valid source is present:
 *  - text-file / recording without an attached file -> "file-required"
 *  - link without a (non-empty) link value          -> "link-required"
 *  - missing or unknown sourceType                   -> "diagram-generation"
 */
export function requiredSourceError(input: RequiredSourceInput): RequiredSourceError | null {
  const { sourceType, hasFile, link } = input;

  if (sourceType === "text-file" || sourceType === "recording") {
    return hasFile ? null : "file-required";
  }

  if (sourceType === "link") {
    return link.trim() ? null : "link-required";
  }

  return "diagram-generation";
}
