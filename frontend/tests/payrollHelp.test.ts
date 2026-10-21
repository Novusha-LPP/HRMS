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

test("each payroll tab has help that explains how the numbers are worked out", () => {
  for (const topic of ["payroll-salaries", "payroll-structures", "payroll-components", "payroll-statutory"] as const) {
    const help = usageHelp[topic];
    assert.ok(help, `${topic} must exist`);
    assert.ok(help.steps.length >= 3, `${topic} needs steps`);
    assert.ok(help.calculation && help.calculation.items.length >= 3, `${topic} needs a calculation section`);
    assert.ok(help.examples && help.examples.length >= 1, `${topic} needs a worked example`);
    for (const example of help.examples ?? []) assert.ok(example.rows.length >= 3);
  }
});

test("the worked examples quote the figures the calculator produces", () => {
  const rows = (usageHelp["payroll-structures"].examples ?? []).flatMap((e) => e.rows.map((r) => r.join(" ")));
  const text = rows.join("\n");
  for (const figure of ["₹13,200", "₹46,400", "₹4,208", "₹592", "₹137", "₹16,871"]) assert.ok(text.includes(figure), figure);
});

test("leavers and rejoin help explain the choices with examples", () => {
  const leavers = usageHelp.leavers;
  assert.ok(leavers.steps.length >= 4 && (leavers.examples?.length ?? 0) >= 2);
  const rows = (leavers.examples ?? []).flatMap((e) => e.rows.map((r) => r.join(" "))).join("\n");
  assert.match(rows, /4 days/);
  assert.match(rows, /6 days/);
  assert.match(usageHelp.rejoin.note, /rehire them/i);
  assert.ok((usageHelp.rejoin.calculation?.items.length ?? 0) >= 3);
});
