function canonicalize(value: unknown, seen: Set<object>): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Canonical JSON only supports finite numbers");
    return Object.is(value, -0) ? 0 : value;
  }
  if (Array.isArray(value)) return value.map((item) => canonicalize(item, seen));
  if (typeof value !== "object") {
    throw new TypeError("Canonical JSON only supports JSON values");
  }
  if (seen.has(value)) throw new TypeError("Canonical JSON does not support cycles");

  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError("Canonical JSON only supports plain objects");
  }

  seen.add(value);
  const result: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) {
    const item = (value as Record<string, unknown>)[key];
    if (item === undefined) throw new TypeError("Canonical JSON does not support undefined");
    result[key] = canonicalize(item, seen);
  }
  seen.delete(value);
  return result;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value, new Set()));
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function canonicalSha256(value: unknown): Promise<string> {
  return sha256Hex(canonicalJson(value));
}
