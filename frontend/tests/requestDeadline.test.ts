import assert from "node:assert/strict";
import { test } from "node:test";
import { withRequestDeadline } from "../src/lib/requestDeadline.ts";

test("deadline aborts a stalled operation", async () => {
  await assert.rejects(withRequestDeadline((signal) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason));
  }), undefined, 5), /timed out/);
});
test("caller cancellation is preserved", async () => {
  const controller = new AbortController();
  controller.abort(new Error("Cancelled"));
  await assert.rejects(withRequestDeadline(async (signal) => {
    signal.throwIfAborted(); return 1;
  }, controller.signal), /Cancelled/);
});
