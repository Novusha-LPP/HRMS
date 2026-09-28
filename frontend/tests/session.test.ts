import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { resetSessionCache } from "../src/lib/session.ts";

test("account changes clear fresh private data and fetch the new identity", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
  client.setQueryData(["my-profile"], { name: "old identity" });
  resetSessionCache(client);
  assert.equal(client.getQueryData(["my-profile"]), undefined);
  const result = await client.fetchQuery({ queryKey: ["my-profile"], queryFn: async () => ({ name: "new identity" }) });
  assert.equal(result.name, "new identity");
  client.clear();
});

test("an old in-flight request cannot repopulate the cleared cache", async () => {
  const client = new QueryClient();
  let complete!: (value: string) => void;
  const request = client.fetchQuery({ queryKey: ["employees"], queryFn: () => new Promise<string>(r => { complete = r; }) }).catch(() => undefined);
  resetSessionCache(client);
  complete("private old data");
  await request;
  assert.equal(client.getQueryData(["employees"]), undefined);
  client.clear();
});
