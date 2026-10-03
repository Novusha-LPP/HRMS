import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// The widget catalog lives in the backend; the web app maps each id to a component.
// A widget added on one side only would be offered but never render (or never be offered).
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("every backend widget has a component, and every component a backend widget", () => {
  // Only the widget grid's catalog; OVERVIEW_CATALOG is rendered by HRMSDashboardView.
  const catalog = read("../../backend/src/hrms/modules/dashboard/widgets.py").split("OVERVIEW_CATALOG")[0];
  const backend = new Set([...catalog.matchAll(/^\s+Widget\("([a-z_]+)"/gm)].map((m) => m[1]));
  const registry = read("../src/components/dashboard/registry.ts");
  const frontend = new Set([...registry.matchAll(/^\s+([a-z_]+): [A-Z]\w+,$/gm)].map((m) => m[1]));

  assert.ok(backend.size >= 10, `parsed ${backend.size} backend widgets — has the catalog format changed?`);
  assert.deepEqual([...frontend].sort(), [...backend].sort());
});
