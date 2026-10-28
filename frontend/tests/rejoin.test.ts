import assert from "node:assert/strict";
import { test } from "node:test";
import { buildRejoinChoice, describeGap, describeSettlement, findPossibleDuplicates } from "../src/lib/rejoin.ts";

test("only what HR actually set is sent, so the company default applies otherwise", () => {
  assert.deepEqual(buildRejoinChoice({ mode: "", condoned: false, reason: "  ", gratuityPaid: false }), {});
  assert.deepEqual(
    buildRejoinChoice({ mode: "FRESH", condoned: false, reason: " New contract ", gratuityPaid: true }),
    { mode: "FRESH", reason: "New contract", gratuity_paid_at_exit: true },
  );
  assert.deepEqual(
    buildRejoinChoice({ mode: "CONTINUE", condoned: true, reason: "Director approved", gratuityPaid: false }),
    { mode: "CONTINUE", break_condoned: true, reason: "Director approved" },
  );
});

test("the gap reads naturally", () => {
  assert.equal(describeGap(null), "Unknown");
  assert.equal(describeGap(0), "Same day");
  assert.equal(describeGap(1), "1 day");
  assert.equal(describeGap(45), "45 days");
  assert.equal(describeGap(-3), "Before they left");
});

test("a settlement line says what happens to each part of the balance", () => {
  const base = { leave_type_id: "lt_1", leave_type_name: "Annual", unused_days: 10, note: null, hold_expires_on: null };
  assert.equal(describeSettlement({ ...base, action: "ENCASH", encash_days: 4, lapse_days: 6, held_days: 0 }), "4 days paid out, 6 days lapses");
  assert.equal(describeSettlement({ ...base, action: "LAPSE", encash_days: 0, lapse_days: 1, held_days: 0 }), "1 day lapses");
  assert.equal(
    describeSettlement({ ...base, action: "HOLD", encash_days: 0, lapse_days: 0, held_days: 10.5, hold_expires_on: "2026-12-01" }),
    "10.5 days held until 2026-12-01",
  );
});

const person = (over: object) => ({
  id: "emp_1", first_name: "Binu", last_name: "Singh", full_name: "Binu Singh",
  employee_number: "E1", employment_state: "SEPARATED", date_of_birth: null, ...over,
});

test("the same name is flagged, and a different birth date clears it", () => {
  const people = [person({}), person({ id: "emp_2", first_name: "Asha", full_name: "Asha Singh" })];
  assert.deepEqual(findPossibleDuplicates(people, { first: " binu ", last: "SINGH", dob: "" }).map((p) => p.id), ["emp_1"]);
  assert.equal(findPossibleDuplicates(people, { first: "Binu", last: "Singh", dob: "1990-01-01" }).length, 1); // dob unknown on file
  const known = [person({ date_of_birth: "1985-05-05" })];
  assert.equal(findPossibleDuplicates(known, { first: "Binu", last: "Singh", dob: "1990-01-01" }).length, 0);
  assert.equal(findPossibleDuplicates(known, { first: "Binu", last: "Singh", dob: "1985-05-05" }).length, 1);
  assert.deepEqual(findPossibleDuplicates(people, { first: "", last: "Singh", dob: "" }), []);
});

import { describeService } from "../src/lib/rejoin.ts";

test("earlier service reads in years and months", () => {
  assert.equal(describeService(0), "Under a month");
  assert.equal(describeService(5), "5 months");
  assert.equal(describeService(12), "1 year");
  assert.equal(describeService(38), "3 years 2 months");
});
