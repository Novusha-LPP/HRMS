/** Store only the acknowledged business date, separately for every employee account. */
const acknowledged = new Map<string, string>();

export function celebrationStorageKey(tenantId: string, userId: string, employmentId: string): string {
  return `hrms_celebrations:${tenantId}:${userId}:${employmentId}`;
}

export function celebrationsAcknowledged(key: string, date: string): boolean {
  if (acknowledged.get(key) === date) return true;
  try { return localStorage.getItem(key) === date; } catch { return false; }
}

export function acknowledgeCelebrations(key: string, date: string): void {
  acknowledged.set(key, date);
  try { localStorage.setItem(key, date); } catch { /* The current page still remembers dismissal. */ }
}
