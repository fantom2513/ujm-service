export class RenderQueue {
  private tail: Promise<void> = Promise.resolve();

  run<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.tail.then(operation);
    this.tail = next.then(
      () => undefined,
      () => undefined
    );
    return next;
  }
}
