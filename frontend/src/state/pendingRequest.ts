import type { PendingTurn } from "../../../shared/types/index.ts";

type StoredValue = string | { blob: Blob; filename: string };
type StoredRequest = { kind: PendingTurn["kind"]; entries: [string, StoredValue][] };
const DATABASE = "copilot-mermaid-pending-v1";
const STORE = "requests";

async function accessRequest<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
  if (!globalThis.indexedDB) return undefined;
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = work(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

export async function savePendingRequest(kind: PendingTurn["kind"], body: FormData): Promise<void> {
  const entries: StoredRequest["entries"] = [...body.entries()].map(([key, value]) => [
    key, typeof value === "string" ? value : { blob: value, filename: value.name },
  ]);
  try {
    await accessRequest("readwrite", store => store.put({ kind, entries }, String(body.get("requestId"))));
  } catch (error) {
    // Storage may be disabled or full. The current tab can still retry with
    // its original FormData; a restored tab will explain if it cannot.
    console.warn("Could not save pending request for reload recovery", error);
  }
}

export async function loadPendingRequest(pending: PendingTurn): Promise<FormData | undefined> {
  let stored: StoredRequest | undefined;
  try {
    stored = await accessRequest<StoredRequest>("readonly", store => store.get(pending.requestId));
  } catch {
    return undefined;
  }
  if (!stored || stored.kind !== pending.kind) return undefined;
  const body = new FormData();
  for (const [key, value] of stored.entries) {
    if (typeof value === "string") body.append(key, value);
    else body.append(key, value.blob, value.filename);
  }
  if (body.get("requestId") !== pending.requestId) return undefined;
  if (pending.kind === "chat" && body.get("sessionId") !== pending.sessionId) return undefined;
  return body;
}

export async function forgetPendingRequest(requestId: string): Promise<void> {
  try {
    await accessRequest("readwrite", store => store.delete(requestId));
  } catch (error) {
    console.warn("Could not remove completed pending request", error);
  }
}
