import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

import {
  CONTENT_SECURITY_POLICY_REPORT_ONLY,
  SECURITY_HEADERS,
  createSecurityHeaderRules,
} from "../config/security-headers.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  server: { middlewareMode: true },
});

after(async () => vite.close());

test("Next and Vinext receive the shared security-header rules", async () => {
  const { default: nextConfig } = await vite.ssrLoadModule("/next.config.ts");
  assert.equal(typeof nextConfig.headers, "function");
  assert.deepEqual(await nextConfig.headers(), createSecurityHeaderRules());

  const [rule] = createSecurityHeaderRules();
  assert.equal(rule.source, "/:path*");
  assert.deepEqual(rule.headers, SECURITY_HEADERS);
  assert.equal(new Set(rule.headers.map(({ key }) => key.toLowerCase())).size, rule.headers.length);
});

test("enforces low-risk headers while CSP remains report-only", () => {
  const headers = new Map(SECURITY_HEADERS.map(({ key, value }) => [key.toLowerCase(), value]));

  assert.equal(headers.get("strict-transport-security"), "max-age=31536000");
  assert.equal(headers.get("x-content-type-options"), "nosniff");
  assert.equal(headers.get("referrer-policy"), "strict-origin-when-cross-origin");
  assert.match(headers.get("permissions-policy"), /camera=\(\)/);
  assert.equal(headers.has("content-security-policy"), false);
  assert.equal(headers.has("x-frame-options"), false);
  assert.equal(headers.has("cross-origin-opener-policy"), false);
});

test("report-only CSP is narrow and allows the known Steam image origin", () => {
  assert.match(CONTENT_SECURITY_POLICY_REPORT_ONLY, /script-src 'self'/);
  assert.doesNotMatch(CONTENT_SECURITY_POLICY_REPORT_ONLY, /script-src[^;]*'unsafe-(?:inline|eval)'/);
  assert.match(CONTENT_SECURITY_POLICY_REPORT_ONLY, /frame-ancestors 'none'/);
  assert.match(
    CONTENT_SECURITY_POLICY_REPORT_ONLY,
    /img-src[^;]*https:\/\/cdn\.cloudflare\.steamstatic\.com/,
  );
  assert.doesNotMatch(CONTENT_SECURITY_POLICY_REPORT_ONLY, /(?:^|\s)\*(?:\s|;|$)/);
});

test("static assets repeat every shared security header before the Worker", async () => {
  const staticHeaders = await readFile(new URL("../public/_headers", import.meta.url), "utf8");
  assert.match(staticHeaders, /^\/\*$/m);
  assert.match(staticHeaders, /^\/_next\/static\/\*$/m);
  assert.match(staticHeaders, /Cache-Control: public, max-age=31536000, immutable/);
  for (const { key, value } of SECURITY_HEADERS) {
    assert.ok(
      staticHeaders.includes(`  ${key}: ${value}`),
      `public/_headers is missing ${key}`,
    );
  }
});
