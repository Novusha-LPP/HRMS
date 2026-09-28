import type { QueryClient } from "@tanstack/react-query";

/** Destroy the prior identity's requests and cached data before publishing a new session. */
export function resetSessionCache(client: QueryClient) {
  void client.cancelQueries();
  client.clear();
}
