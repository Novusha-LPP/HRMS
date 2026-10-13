import assert from "node:assert/strict";
import { test } from "node:test";
import { usageHelp } from "../src/lib/usageHelp.ts";

test("payroll usage help defines all required setup and assignment steps", () => {
  const help = usageHelp.payroll;
  assert.ok(help, "payroll topic must exist in usageHelp");
  assert.equal(help.steps.length, 4);

  assert.equal(help.steps[0].title, "Load the PF and ESIC values");
  assert.match(help.steps[0].description, /defaults/i);

  assert.equal(help.steps[1].title, "Have them verified");
  assert.match(help.steps[1].description, /reviewer/i);

  assert.equal(help.steps[2].title, "Set up a salary structure");
  assert.match(help.steps[2].description, /structure/i);

  assert.equal(help.steps[3].title, "Assign salaries to employees");
  assert.match(help.steps[3].description, /salaries|employees/i);
});
