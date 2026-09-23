export class RenderSequence {
  private current = 0;

  start(): number {
    this.current += 1;
    return this.current;
  }

  isCurrent(token: number): boolean {
    return token === this.current;
  }
}
