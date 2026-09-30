/** Client-side password rules. The server enforces the same ones; this just explains them early. */

export const MIN_PASSWORD_LENGTH = 8;
/** bcrypt ignores everything past 72 *bytes* — a 30-emoji password is 120. */
export const MAX_PASSWORD_BYTES = 72;

export function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).length;
}

/** null when the password is acceptable, otherwise a sentence saying what to change. */
export function passwordProblem(next: string, current?: string): string | null {
  if (next.length < MIN_PASSWORD_LENGTH) return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (utf8Bytes(next) > MAX_PASSWORD_BYTES) {
    return `That password is too long (at most ${MAX_PASSWORD_BYTES} bytes — non-English characters and emoji count as several).`;
  }
  if (current !== undefined && next === current) return "Choose a password different from your current one.";
  return null;
}

const LOWER = "abcdefghijkmnpqrstuvwxyz"; // no l, o — easy to misread when read out or typed
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const DIGITS = "23456789";
const SYMBOLS = "@#$%&*?";

/** A random temporary password for an admin to hand over, using the browser's CSPRNG. */
export function generateTempPassword(length = 12, random: (n: number) => number = secureRandomInt): string {
  const sets = [LOWER, UPPER, DIGITS, SYMBOLS];
  const all = sets.join("");
  const chars = sets.map((s) => s[random(s.length)]); // at least one of each kind
  while (chars.length < length) chars.push(all[random(all.length)]);
  for (let i = chars.length - 1; i > 0; i--) { // Fisher–Yates
    const j = random(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

function secureRandomInt(max: number): number {
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    // Rejection sampling, so the result is uniform rather than biased by the modulo.
    const limit = Math.floor(0x100000000 / max) * max;
    const buf = new Uint32Array(1);
    do { crypto.getRandomValues(buf); } while (buf[0] >= limit);
    return buf[0] % max;
  }
  return Math.floor(Math.random() * max);
}
