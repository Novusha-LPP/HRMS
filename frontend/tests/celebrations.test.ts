import assert from "node:assert/strict";
import { test } from "node:test";
import { acknowledgeCelebrations, celebrationStorageKey, celebrationsAcknowledged } from "../src/lib/celebrations.ts";

test("celebration acknowledgment is isolated by tenant, user and employment", () => {
  const keys = [
    celebrationStorageKey("tenant-a", "user-a", "employment-a"),
    celebrationStorageKey("tenant-b", "user-a", "employment-a"),
    celebrationStorageKey("tenant-a", "user-b", "employment-a"),
    celebrationStorageKey("tenant-a", "user-a", "employment-b"),
  ];
  assert.equal(new Set(keys).size, 4);
  acknowledgeCelebrations(keys[0], "2026-10-09");
  assert.equal(celebrationsAcknowledged(keys[0], "2026-10-09"), true);
  for (const key of keys.slice(1)) assert.equal(celebrationsAcknowledged(key, "2026-10-09"), false);
  assert.equal(celebrationsAcknowledged(keys[0], "2026-10-10"), false);
});

test("the only persisted value is the server business date", t => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  } });
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
  const key = celebrationStorageKey("persist-tenant", "persist-user", "persist-employment");
  acknowledgeCelebrations(key, "2026-10-09");
  assert.deepEqual([...values], [[key, "2026-10-09"]]);
  values.set(celebrationStorageKey("another", "account", "employment"), "2026-10-09");
  assert.equal(celebrationsAcknowledged(celebrationStorageKey("another", "account", "employment"), "2026-10-09"), true);
});

test("blocked browser storage still remembers dismissal for the current page", t => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, get() { throw new Error("Storage blocked"); } });
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor);
    else Reflect.deleteProperty(globalThis, "localStorage");
  });
  const key = celebrationStorageKey("blocked-tenant", "blocked-user", "blocked-employment");
  assert.equal(celebrationsAcknowledged(key, "2026-10-09"), false);
  assert.doesNotThrow(() => acknowledgeCelebrations(key, "2026-10-09"));
  assert.equal(celebrationsAcknowledged(key, "2026-10-09"), true);
  assert.equal(celebrationsAcknowledged(key, "2026-10-10"), false);
});
