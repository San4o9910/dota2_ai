import { env } from "cloudflare:workers";

import type { YooKassaCredentials } from "@/lib/payments/yookassa";
import {
  parsePaymentRuntime,
  type PaymentGate,
  type PaymentRuntimeEnvironment,
} from "@/lib/payments/runtime-config";

function runtimeConfig() {
  return parsePaymentRuntime(env as unknown as PaymentRuntimeEnvironment);
}

export function paymentsEnabled() {
  return runtimeConfig().paymentsEnabled;
}

export function paymentSettlementEnabled() {
  return runtimeConfig().settlementEnabled;
}

export function analysisRuntimeEnabled() {
  return runtimeConfig().analysisRuntimeEnabled;
}

export function analysisFulfillmentEnabled() {
  return runtimeConfig().analysisFulfillmentEnabled;
}

export function getPaymentRuntimeIdentity() {
  const config = runtimeConfig();
  if (!config.environment || !config.appOrigin || !config.paymentMode || !config.shopId) {
    throw new Error("Payment runtime identity is not configured");
  }
  return {
    environment: config.environment,
    appOrigin: config.appOrigin,
    paymentMode: config.paymentMode,
    providerShopId: config.shopId,
  };
}

export function getPaymentSettlementIdentity() {
  const config = runtimeConfig();
  if (!config.environment || !config.paymentMode || !config.shopId) {
    throw new Error("Payment settlement identity is not configured");
  }
  return {
    environment: config.environment,
    paymentMode: config.paymentMode,
    providerShopId: config.shopId,
  };
}

export function getYooKassaCredentials(
  gate: PaymentGate = "checkout",
): YooKassaCredentials {
  const config = runtimeConfig();
  const gateEnabled = gate === "checkout"
    ? config.paymentsEnabled
    : config.settlementEnabled;
  if (!gateEnabled || !config.shopId || !config.secretKey) {
    throw new Error(
      gate === "checkout"
        ? "Payment checkout is not enabled"
        : "Payment settlement is not enabled",
    );
  }
  return { shopId: config.shopId, secretKey: config.secretKey };
}
