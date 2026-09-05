export type BillingRequestIdentity = {
  orderId: string;
  userId: string;
  checkoutAttemptId: string;
  productCode: string;
  productVersion: string;
  matchId: string | null;
  amountKopecks: number;
  currency: "RUB";
  grantAnalyses: number;
  grantCoachQuestions: number;
  durationDays: number | null;
  environment: string;
  paymentMode: "test" | "live";
  provider: "yookassa";
  providerShopId: string;
  providerIdempotencyKey: string;
};

export const BILLING_ORDER_INTEGRITY_VERSION = "billing-order-integrity.v1";

export function serializeBillingRequest(input: BillingRequestIdentity) {
  return JSON.stringify({
    integrityVersion: BILLING_ORDER_INTEGRITY_VERSION,
    orderId: input.orderId,
    userId: input.userId,
    checkoutAttemptId: input.checkoutAttemptId,
    productCode: input.productCode,
    productVersion: input.productVersion,
    matchId: input.matchId,
    amountKopecks: input.amountKopecks,
    currency: input.currency,
    grantAnalyses: input.grantAnalyses,
    grantCoachQuestions: input.grantCoachQuestions,
    durationDays: input.durationDays,
    environment: input.environment,
    paymentMode: input.paymentMode,
    provider: input.provider,
    providerShopId: input.providerShopId,
    providerIdempotencyKey: input.providerIdempotencyKey,
  });
}

export async function billingRequestHash(input: BillingRequestIdentity) {
  const bytes = new TextEncoder().encode(serializeBillingRequest(input));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
