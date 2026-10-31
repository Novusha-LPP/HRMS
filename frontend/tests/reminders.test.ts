import assert from "node:assert/strict";
import { test } from "node:test";
import { describeOffsets, describeRule, describeTime, offsetsFor } from "../src/lib/reminders.ts";

test("the presets give the same days the server uses", () => {
  assert.deepEqual(offsetsFor("SAME_DAY", 0, []), [0]);
  assert.deepEqual(offsetsFor("ONE_DAY_BEFORE", 0, []), [1]);
  assert.deepEqual(offsetsFor("CONTINUOUS", 3, []), [3, 2, 1, 0]);
  assert.deepEqual(offsetsFor("ALTERNATE_DAYS", 5, []), [5, 3, 1, 0]);
  assert.deepEqual(offsetsFor("ALTERNATE_DAYS", 4, []), [4, 2, 0]);
  assert.deepEqual(offsetsFor("CUSTOM", 0, [1, 7, 7, 0, 99, -1]), [7, 1, 0]);
});

test("schedules read as plain sentences", () => {
  assert.equal(describeOffsets([3, 1, 0], "birthday"), "3 days before, 1 day before and on the birthday");
  assert.equal(describeOffsets([0], "joining day"), "on the joining day");
  assert.equal(describeOffsets([1], "birthday"), "1 day before the birthday");
  assert.equal(describeOffsets([], "birthday"), "on no day yet");
  assert.equal(describeTime("09:00"), "9:00 AM");
  assert.equal(describeTime("00:05:00"), "12:05 AM");
  assert.equal(describeTime("17:30"), "5:30 PM");
});

test("a rule is described in one sentence", () => {
  const sentence = describeRule({
    trigger: "BIRTHDAY", frequency: "ALTERNATE_DAYS", days_before: 3, custom_offsets: [], send_time: "09:00",
    notify_employee: true, notify_manager: true, notify_everyone: false, extra_emails: ["hr@x.com"],
  });
  assert.equal(
    sentence,
    "Email the person themselves, their manager and 1 other address 3 days before, 1 day before and on the birthday, at 9:00 AM. The person’s own message is sent on the day only.",
  );
});
