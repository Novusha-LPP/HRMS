import assert from "node:assert/strict";
import { test } from "node:test";
import { createPhotoCache } from "../src/lib/photoCache.ts";

function harness(load: (id: string) => Promise<Blob | null>, extra: object = {}) {
  const calls: string[] = [];
  const revoked: string[] = [];
  let clock = 0;
  const cache = createPhotoCache({
    load: (id) => { calls.push(id); return load(id); },
    createUrl: (blob) => `blob:${(blob as unknown as { tag: string }).tag}`,
    revokeUrl: (url) => revoked.push(url),
    now: () => clock,
    ...extra,
  });
  return { cache, calls, revoked, tick: (ms: number) => { clock += ms; } };
}

const photo = (tag: string) => ({ tag }) as unknown as Blob;

test("the same person is requested once however many avatars show them", async () => {
  const { cache, calls } = harness(async (id) => photo(id));
  const urls = await Promise.all([cache.get("a"), cache.get("a"), cache.get("a")]);
  assert.deepEqual(urls, ["blob:a", "blob:a", "blob:a"]);
  assert.deepEqual(calls, ["a"]);
  assert.equal(cache.peek("a"), "blob:a");
  assert.equal(cache.peek("nobody"), null);
});

test("people without a photo are remembered as having none", async () => {
  const { cache, calls } = harness(async () => null);
  assert.equal(await cache.get("a"), null);
  assert.equal(await cache.get("a"), null);
  assert.deepEqual(calls, ["a"]);
});

test("a result expires and is asked for again, releasing the old address", async () => {
  const { cache, calls, revoked, tick } = harness(async (id) => photo(id), { ttlMs: 1000 });
  await cache.get("a");
  tick(999);
  await cache.get("a");
  assert.equal(calls.length, 1);
  tick(2);
  await cache.get("a");
  assert.equal(calls.length, 2);
  assert.deepEqual(revoked, ["blob:a"]);
});

test("a failure is retried soon and does not break other people", async () => {
  let fail = true;
  const { cache, calls, tick } = harness(async (id) => {
    if (id === "bad" && fail) throw new Error("network");
    return photo(id);
  }, { failureTtlMs: 100 });
  assert.equal(await cache.get("bad"), null);
  assert.equal(await cache.get("good"), "blob:good");
  assert.equal(await cache.get("bad"), null);
  assert.equal(calls.filter((c) => c === "bad").length, 1);
  fail = false;
  tick(101);
  assert.equal(await cache.get("bad"), "blob:bad");
});

test("only a few photos load at a time", async () => {
  let active = 0;
  let peak = 0;
  const { cache } = harness(async (id) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
    return photo(id);
  }, { concurrency: 3 });
  await Promise.all(Array.from({ length: 12 }, (_, i) => cache.get(`p${i}`)));
  assert.equal(peak, 3);
});

test("the cache is bounded and clearing releases every address", async () => {
  const { cache, revoked } = harness(async (id) => photo(id), { maxEntries: 3 });
  for (const id of ["a", "b", "c", "d"]) await cache.get(id);
  assert.equal(cache.size(), 3);
  assert.deepEqual(revoked, ["blob:a"]);
  cache.clear();
  assert.equal(cache.size(), 0);
  assert.deepEqual(revoked.sort(), ["blob:a", "blob:b", "blob:c", "blob:d"]);
});
