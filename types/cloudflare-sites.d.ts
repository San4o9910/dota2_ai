/**
 * Compile-time view of bindings injected by the Sites control plane.
 *
 * This declaration does not provision bindings. D1 remains optional here so
 * local tooling and the existing runtime availability check agree. Worker
 * runtime globals are generated into ignored local state by `npm run
 * types:generate`; no deployment bindings are inferred or provisioned here.
 */
declare namespace Cloudflare {
  interface Env {
    DB?: D1Database;
    REPLAYS?: R2Bucket;
    REPLAY_WORKER_TOKEN?: string;
    APP_ENVIRONMENT?: string;
    APP_ORIGIN?: string;
    SCAN_RUNTIME_ENABLED?: string;
    SCAN_RATE_LIMIT_SECRET?: string;
    ANALYSIS_RUNTIME_ENABLED?: string;
    ANALYSIS_FULFILLMENT_ENABLED?: string;
    OPENAI_API_KEY?: string;
    OPENAI_MODEL?: string;
    OPENAI_ALLOWED_MODELS?: string;
    PAYMENTS_ENABLED?: string;
    PAYMENT_SETTLEMENT_ENABLED?: string;
    PAYMENT_MODE?: string;
    YOOKASSA_TEST_SHOP_ID?: string;
    YOOKASSA_TEST_SECRET_KEY?: string;
    YOOKASSA_LIVE_SHOP_ID?: string;
    YOOKASSA_LIVE_SECRET_KEY?: string;
  }
}
