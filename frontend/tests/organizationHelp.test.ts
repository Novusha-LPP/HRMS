import assert from "node:assert/strict";
import { test } from "node:test";
import { usageHelp } from "../src/lib/usageHelp.ts";
import type { UsageHelpTopic } from "../src/lib/usageHelp.ts";

test("organization modules have dedicated usage help topics with complete instructions", () => {
  const orgTopics: UsageHelpTopic[] = [
    "organization",
    "org-overview",
    "companies",
    "departments",
    "locations",
    "jobs",
    "grades",
    "positions",
    "cost-centres",
    "employee-ids",
    "company-admins",
  ];

  for (const topic of orgTopics) {
    const help = usageHelp[topic];
    assert.ok(help, `${topic} topic must exist in usageHelp`);
    assert.ok(help.title && help.title.length > 5, `${topic} must have a descriptive title`);
    assert.ok(help.introduction && help.introduction.length > 10, `${topic} must have an introduction explaining what it is`);
    assert.ok(help.steps && help.steps.length >= 3, `${topic} must have at least 3 step-by-step instructions`);
    assert.ok(help.note && help.note.length > 10, `${topic} must have a guidance note`);

    for (const step of help.steps) {
      assert.ok(step.title && step.title.length > 0, `${topic} step must have a title`);
      assert.ok(step.description && step.description.length > 10, `${topic} step must have a detailed description`);
    }
  }
});
