import { env } from "cloudflare:workers";

import type { YooKassaCredentials } from "@/lib/payments/yookassa";

type PaymentEnvironment = {
  ANALYSIS_FULFILLMENT_ENABLED?: string;
  PAYMENTS_ENABLED?: string;
  YOOKASSA_SHOP_ID?: string;
  YOOKASSA_SECRET_KEY?: string;
};

function paymentEnvironment() {
  return env as unknown as PaymentEnvironment;
}

export function paymentsEnabled() {
  const runtime = paymentEnvironment();
  return runtime.PAYMENTS_ENABLED === "true"
    && runtime.ANALYSIS_FULFILLMENT_ENABLED === "true"
    && Boolean(runtime.YOOKASSA_SHOP_ID)
    && Boolean(runtime.YOOKASSA_SECRET_KEY);
}

export function getYooKassaCredentials(): YooKassaCredentials {
  const runtime = paymentEnvironment();
  if (!paymentsEnabled()) {
    throw new Error("Payments are not enabled");
  }
  return {
    shopId: runtime.YOOKASSA_SHOP_ID!,
    secretKey: runtime.YOOKASSA_SECRET_KEY!,
  };
}
