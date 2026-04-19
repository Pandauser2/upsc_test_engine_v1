import "@testing-library/jest-dom/vitest";

class LocalStorageMock {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }
}

const ls = new LocalStorageMock();
Object.defineProperty(globalThis, "localStorage", {
  value: ls,
  writable: true,
});

