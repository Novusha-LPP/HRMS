import assert from "node:assert/strict";
import { test } from "node:test";
import { generateTempPassword, passwordProblem, utf8Bytes } from "../src/lib/password.ts";

test("passwords are checked for length, byte size and reuse", () => {
  assert.match(passwordProblem("short")!, /at least 8/);
  assert.equal(passwordProblem("long-enough-1"), null);
  assert.equal(passwordProblem("😀".repeat(30)) !== null, true); // 30 characters, 120 bytes
  assert.equal(utf8Bytes("😀".repeat(30)), 120);
  assert.match(passwordProblem("Same-pass-1", "Same-pass-1")!, /different/);
  assert.equal(passwordProblem("New-pass-12", "Old-pass-12"), null);
});

test("a generated temporary password always satisfies the rules and mixes character kinds", () => {
  for (let i = 0; i < 200; i++) {
    const pw = generateTempPassword();
    assert.equal(pw.length, 12);
    assert.equal(passwordProblem(pw), null);
    assert.match(pw, /[a-z]/); assert.match(pw, /[A-Z]/); assert.match(pw, /[2-9]/); assert.match(pw, /[@#$%&*?]/);
    assert.doesNotMatch(pw, /[lIO01]/); // nothing easy to misread
  }
  assert.notEqual(generateTempPassword(), generateTempPassword());
});

test("the temporary password generator is unbiased enough to use every symbol", () => {
  const seen = new Set<string>();
  for (let i = 0; i < 400; i++) for (const c of generateTempPassword(16)) seen.add(c);
  assert.ok(seen.size >= 40, `only ${seen.size} distinct characters appeared`);
});
