/**
 * A small cache in front of the profile-photo requests.
 *
 * A screen can show dozens of avatars, and the same person often appears many times. Each
 * person's photo is requested once at a time and shared; a few load at once; the result (a
 * photo, or "none") is remembered briefly; and the cache is cleared when the session changes.
 * No network or browser code lives here so it can be tested on its own.
 */

export type PhotoLoader = (id: string) => Promise<Blob | null>;

export interface PhotoCacheOptions {
  load: PhotoLoader;
  createUrl: (blob: Blob) => string;
  revokeUrl: (url: string) => void;
  now?: () => number;
  /** How long a result is trusted before it is asked for again. */
  ttlMs?: number;
  /** How long a failure is remembered (short, so a hiccup is retried soon). */
  failureTtlMs?: number;
  maxEntries?: number;
  concurrency?: number;
}

interface Entry {
  promise: Promise<string | null>;
  url: string | null;
  settled: boolean;
  expires: number;
}

export function createPhotoCache(options: PhotoCacheOptions) {
  const now = options.now ?? Date.now;
  const ttl = options.ttlMs ?? 5 * 60_000;
  const failureTtl = options.failureTtlMs ?? 15_000;
  const maxEntries = options.maxEntries ?? 300;
  const concurrency = options.concurrency ?? 6;
  const entries = new Map<string, Entry>();
  const waiting: Array<() => void> = [];
  let running = 0;

  function release() {
    running -= 1;
    waiting.shift()?.();
  }

  async function slot() {
    if (running >= concurrency) await new Promise<void>((resolve) => waiting.push(resolve));
    running += 1;
  }

  function drop(id: string) {
    const entry = entries.get(id);
    if (entry?.url) options.revokeUrl(entry.url);
    entries.delete(id);
  }

  function get(id: string): Promise<string | null> {
    const existing = entries.get(id);
    if (existing && existing.expires > now()) return existing.promise;
    if (existing) drop(id);
    while (entries.size >= maxEntries) {
      const oldest = entries.keys().next().value;
      if (oldest === undefined) break;
      drop(oldest);
    }
    const entry: Entry = { promise: Promise.resolve(null), url: null, settled: false, expires: Infinity };
    entry.promise = (async () => {
      await slot();
      try {
        const blob = await options.load(id);
        entry.url = blob ? options.createUrl(blob) : null;
        entry.expires = now() + ttl;
      } catch {
        entry.url = null;
        entry.expires = now() + failureTtl;
      } finally {
        entry.settled = true;
        release();
      }
      return entry.url;
    })();
    entries.set(id, entry);
    return entry.promise;
  }

  /** The photo address if it is already known, so a screen does not flash initials first. */
  function peek(id: string): string | null {
    const entry = entries.get(id);
    return entry && entry.settled && entry.expires > now() ? entry.url : null;
  }

  /** Forget one person (their photo changed) so the next look asks the server again. */
  function invalidate(id: string) {
    drop(id);
  }

  function clear() {
    for (const id of [...entries.keys()]) drop(id);
  }

  return { get, peek, invalidate, clear, size: () => entries.size };
}
