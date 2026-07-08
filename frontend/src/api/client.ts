import type { ApiError } from "../types/index.ts";

export async function getConfig(): Promise<{ productHomeUrl: string }> {
  const response = await fetch("/api/config");
  const payload = await response.json();
  return { productHomeUrl: payload.productHomeUrl || "http://localhost:3000/" };
}

export async function generateDiagram(form: FormData): Promise<unknown> {
  return requestJson("/api/generate", form);
}

export async function sendChatMessage(form: FormData): Promise<unknown> {
  return requestJson("/api/chat", form);
}

async function requestJson(url: string, body: FormData): Promise<unknown> {
  const response = await fetch(url, { method: "POST", body });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    const error = payload.error as ApiError;
    throw error;
  }
  return payload.result;
}
