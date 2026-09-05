const RATE_IDENTITY_CONTEXT = "narma-scan-rate-limit.v1\0";

function normalizeIpv4(value: string): string | null {
  const parts = value.split(".");
  if (parts.length !== 4) return null;
  const numbers = parts.map((part) => {
    if (!/^\d{1,3}$/.test(part)) return null;
    const number = Number(part);
    return number >= 0 && number <= 255 ? number : null;
  });
  if (numbers.some((part) => part === null)) return null;
  return numbers.join(".");
}

/** Accepts only Cloudflare's direct connecting-IP header; no proxy fallbacks. */
export function normalizeConnectingIp(value: string | null): string | null {
  const candidate = value?.trim() ?? "";
  if (!candidate || candidate.length > 64 || !/^[0-9a-f.:]+$/i.test(candidate)) return null;
  if (!candidate.includes(":")) return normalizeIpv4(candidate);

  try {
    const hostname = new URL(`http://[${candidate}]/`).hostname;
    const normalized = hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
    return normalized.toLowerCase();
  } catch {
    return null;
  }
}

export async function hashRateLimitIdentity(
  secret: string,
  connectingIp: string,
  windowStart: number,
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${RATE_IDENTITY_CONTEXT}${windowStart}\0${connectingIp}`),
  );
  return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
