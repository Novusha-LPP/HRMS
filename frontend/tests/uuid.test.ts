import assert from "node:assert/strict";
import { test } from "node:test";
import { generateUUID, generateRequestId } from "../src/lib/uuid.ts";

const UUID_V4_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REQ_ID_REGEX = /^req_[0-9a-f]{32}$/i;

test("generateUUID creates valid RFC4122 v4 UUID with standard crypto", () => {
  const id = generateUUID();
  assert.match(id, UUID_V4_REGEX);

  const reqId = generateRequestId();
  assert.match(reqId, REQ_ID_REGEX);
});

test("generateUUID works in non-secure context where crypto.randomUUID is undefined", () => {
  const originalCrypto = globalThis.crypto;
  try {
    // Simulate non-secure browser context (HTTP): crypto exists with getRandomValues, but randomUUID is undefined
    const mockCrypto = {
      getRandomValues: (array: Uint8Array) => originalCrypto.getRandomValues(array),
      randomUUID: undefined,
    } as unknown as Crypto;

    Object.defineProperty(globalThis, "crypto", {
      value: mockCrypto,
      configurable: true,
      writable: true,
    });

    const id = generateUUID();
    assert.match(id, UUID_V4_REGEX);

    const reqId = generateRequestId();
    assert.match(reqId, REQ_ID_REGEX);
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      value: originalCrypto,
      configurable: true,
      writable: true,
    });
  }
});

test("generateUUID falls back gracefully when crypto is completely absent", () => {
  const originalCrypto = globalThis.crypto;
  try {
    Object.defineProperty(globalThis, "crypto", {
      value: undefined,
      configurable: true,
      writable: true,
    });

    const id = generateUUID();
    assert.match(id, UUID_V4_REGEX);

    const reqId = generateRequestId();
    assert.match(reqId, REQ_ID_REGEX);
  } finally {
    Object.defineProperty(globalThis, "crypto", {
      value: originalCrypto,
      configurable: true,
      writable: true,
    });
  }
});

test("generates unique IDs across successive invocations", () => {
  const ids = new Set<string>();
  for (let i = 0; i < 100; i++) {
    ids.add(generateRequestId());
  }
  assert.equal(ids.size, 100);
});
