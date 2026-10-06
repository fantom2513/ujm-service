// IndexedDB boundary for Node tests: records use structured cloning and
// requests complete asynchronously, including their transaction.
export function memoryIndexedDb(): IDBFactory {
  const records = new Map<string, unknown>();
  let created = false;
  const database = {
    objectStoreNames: { contains: () => created },
    createObjectStore: () => { created = true; },
    close: () => {},
    transaction: () => {
      const transaction: any = { error: null };
      const operation = (work: () => unknown) => {
        const request: any = { error: null };
        queueMicrotask(() => {
          request.result = work();
          request.onsuccess?.();
          transaction.oncomplete?.();
        });
        return request;
      };
      transaction.objectStore = () => ({
        put: (value: unknown, key: string) => operation(() => records.set(key, structuredClone(value))),
        get: (key: string) => operation(() => structuredClone(records.get(key))),
        delete: (key: string) => operation(() => records.delete(key)),
      });
      return transaction;
    },
  };
  return {
    open: () => {
      const request: any = { result: database, error: null };
      queueMicrotask(() => {
        if (!created) request.onupgradeneeded?.();
        request.onsuccess?.();
      });
      return request;
    },
  } as unknown as IDBFactory;
}
