import { parseAnalysisRuntime } from "@/lib/analyses/runtime-config";

export type PaymentMode = "test" | "live";
export type PaymentGate = "checkout" | "settlement";

export type PaymentRuntimeEnvironment = {
  APP_ENVIRONMENT?: string;
  APP_ORIGIN?: string;
  ANALYSIS_RUNTIME_ENABLED?: string;
  ANALYSIS_FULFILLMENT_ENABLED?: string;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  OPENAI_ALLOWED_MODELS?: string;
  DB?: D1Database;
  PAYMENTS_ENABLED?: string;
  PAYMENT_SETTLEMENT_ENABLED?: string;
  PAYMENT_MODE?: string;
  YOOKASSA_TEST_SHOP_ID?: string;
  YOOKASSA_TEST_SECRET_KEY?: string;
  YOOKASSA_LIVE_SHOP_ID?: string;
  YOOKASSA_LIVE_SECRET_KEY?: string;
};

export type PaymentRuntimeConfig = {
  environment: string | null;
  appOrigin: string | null;
  paymentMode: PaymentMode | null;
  shopId: string | null;
  secretKey: string | null;
  credentialsConfigured: boolean;
  paymentsEnabled: boolean;
  settlementEnabled: boolean;
  analysisRuntimeEnabled: boolean;
  analysisFulfillmentEnabled: boolean;
  analysisFulfillmentReady: boolean;
  paidCatalogFulfillmentReady: boolean;
};

const ENVIRONMENT = /^[a-z][a-z0-9_-]{1,31}$/;
const SHOP_ID = /^\d{4,32}$/;
const SECRET_KEY = /^[\x21-\x7e]{12,256}$/;
// Every paid catalog item currently grants coach questions. Keep checkout
// structurally locked until that fulfillment workflow exists and is exercised.
const PAID_CATALOG_FULFILLMENT_AVAILABLE = false;

function enabled(value: string | undefined) {
  return value === "true";
}

function configuredCredential(value: string | undefined, minimumLength: number) {
  return typeof value === "string" && value.length >= minimumLength ? value : null;
}

function isD1Database(value: unknown): value is D1Database {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Record<"prepare" | "batch" | "exec", unknown>>;
  return typeof candidate.prepare === "function"
    && typeof candidate.batch === "function"
    && typeof candidate.exec === "function";
}

function canonicalHttpsOrigin(value: string | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:"
      || url.username
      || url.password
      || url.pathname !== "/"
      || url.search
      || url.hash
    ) return null;
    return url.origin;
  } catch {
    return null;
  }
}

/** Pure parser used by runtime code and fail-closed contract tests. */
export function parsePaymentRuntime(
  runtime: PaymentRuntimeEnvironment,
): PaymentRuntimeConfig {
  const environment = typeof runtime.APP_ENVIRONMENT === "string"
    && ENVIRONMENT.test(runtime.APP_ENVIRONMENT)
    ? runtime.APP_ENVIRONMENT
    : null;
  const appOrigin = canonicalHttpsOrigin(runtime.APP_ORIGIN);
  const paymentMode = runtime.PAYMENT_MODE === "test" || runtime.PAYMENT_MODE === "live"
    ? runtime.PAYMENT_MODE
    : null;

  const shopId = paymentMode === "test"
    ? configuredCredential(runtime.YOOKASSA_TEST_SHOP_ID, 4)
    : paymentMode === "live"
      ? configuredCredential(runtime.YOOKASSA_LIVE_SHOP_ID, 4)
      : null;
  const secretKey = paymentMode === "test"
    ? configuredCredential(runtime.YOOKASSA_TEST_SECRET_KEY, 12)
    : paymentMode === "live"
      ? configuredCredential(runtime.YOOKASSA_LIVE_SECRET_KEY, 12)
      : null;
  const credentialsConfigured = Boolean(
    environment
      && paymentMode
      && shopId
      && SHOP_ID.test(shopId)
      && secretKey
      && SECRET_KEY.test(secretKey),
  );
  const analysisRuntimeEnabled = enabled(runtime.ANALYSIS_RUNTIME_ENABLED);
  const analysisFulfillmentEnabled = enabled(runtime.ANALYSIS_FULFILLMENT_ENABLED);
  const analysisFulfillmentReady = parseAnalysisRuntime(runtime).fulfillmentReady
    && isD1Database(runtime.DB);
  const paidCatalogFulfillmentReady = analysisFulfillmentReady
    && PAID_CATALOG_FULFILLMENT_AVAILABLE;
  const settlementEnabled = enabled(runtime.PAYMENT_SETTLEMENT_ENABLED)
    && credentialsConfigured;

  return {
    environment,
    appOrigin,
    paymentMode,
    shopId,
    secretKey,
    credentialsConfigured,
    paymentsEnabled: enabled(runtime.PAYMENTS_ENABLED)
      && paidCatalogFulfillmentReady
      && settlementEnabled
      && Boolean(appOrigin)
      && credentialsConfigured,
    settlementEnabled,
    analysisRuntimeEnabled,
    analysisFulfillmentEnabled,
    analysisFulfillmentReady,
    paidCatalogFulfillmentReady,
  };
}
