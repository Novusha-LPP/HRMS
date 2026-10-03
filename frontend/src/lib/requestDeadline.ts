export async function withRequestDeadline<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal | null,
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(new Error("Request timed out")), timeoutMs);
  try { return await operation(controller.signal); }
  finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
