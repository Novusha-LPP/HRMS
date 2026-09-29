import assert from "node:assert/strict";
import { test } from "node:test";
import { format } from "date-fns";
import { formatDateOnly } from "../src/lib/dates.ts";

test("a birthday is shown on the same day everywhere on Earth", () => {
  const original = process.env.TZ;
  try {
    for (const tz of ["America/Los_Angeles", "Pacific/Honolulu", "UTC", "Asia/Kolkata", "Pacific/Kiritimati"]) {
      process.env.TZ = tz;
      assert.equal(formatDateOnly("1990-03-04"), "4 Mar 1990", tz);
    }
    // …whereas the naive version this replaces is off by a day west of UTC.
    process.env.TZ = "America/Los_Angeles";
    assert.equal(format(new Date("1990-03-04"), "d MMM yyyy"), "3 Mar 1990");
  } finally {
    if (original === undefined) delete process.env.TZ; else process.env.TZ = original;
  }
});
