import { YooKassaError } from "@/lib/payments/yookassa";

export function paymentRouteFailure(error: unknown) {
  return error instanceof YooKassaError
    ? { status: 503 as const, code: "PAYMENT_PROVIDER_UNAVAILABLE" as const }
    : { status: 500 as const, code: "PAYMENT_STORAGE_UNAVAILABLE" as const };
}
