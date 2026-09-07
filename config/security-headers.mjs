export const CONTENT_SECURITY_POLICY_REPORT_ONLY = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://cdn.cloudflare.steamstatic.com",
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
].join("; ");

// These values are deliberately conservative for a Sites-hosted ChatGPT app.
// CSP is report-only until inline Next/Vinext scripts and embedding behavior are
// verified in staging. COOP and X-Frame-Options are intentionally omitted for
// the same reason; both can break host embedding or popup authentication.
export const SECURITY_HEADERS = Object.freeze([
  Object.freeze({
    key: "Content-Security-Policy-Report-Only",
    value: CONTENT_SECURITY_POLICY_REPORT_ONLY,
  }),
  Object.freeze({
    key: "Strict-Transport-Security",
    value: "max-age=31536000",
  }),
  Object.freeze({
    key: "X-Content-Type-Options",
    value: "nosniff",
  }),
  Object.freeze({
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  }),
  Object.freeze({
    key: "Permissions-Policy",
    value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
  }),
]);

export function createSecurityHeaderRules() {
  return [
    {
      source: "/:path*",
      headers: SECURITY_HEADERS.map(({ key, value }) => ({ key, value })),
    },
  ];
}
