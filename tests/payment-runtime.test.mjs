import assert from "node:assert/strict";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

after(async () => vite.close());

const configuredTestRuntime = {
  APP_ENVIRONMENT: "staging",
  APP_ORIGIN: "https://staging.example.test",
  PAYMENT_MODE: "test",
  YOOKASSA_TEST_SHOP_ID: "123456",
  YOOKASSA_TEST_SECRET_KEY: "test_secret_key_123456",
  PAYMENTS_ENABLED: "true",
  PAYMENT_SETTLEMENT_ENABLED: "true",
  ANALYSIS_RUNTIME_ENABLED: "true",
  ANALYSIS_FULFILLMENT_ENABLED: "true",
  OPENAI_API_KEY: "sk-test-abcdefghijklmnopqrstuvwxyz",
  OPENAI_MODEL: "gpt-test-model",
  OPENAI_ALLOWED_MODELS: "gpt-test-model",
  DB: { prepare() {}, batch() {}, exec() {} },
};

test("all feature flags fail closed when absent or malformed", async () => {
  const { parsePaymentRuntime } = await vite.ssrLoadModule(
    "/lib/payments/runtime-config.ts",
  );
  const empty = parsePaymentRuntime({});
  assert.equal(empty.paymentsEnabled, false);
  assert.equal(empty.settlementEnabled, false);
  assert.equal(empty.analysisRuntimeEnabled, false);
  assert.equal(empty.analysisFulfillmentEnabled, false);
  assert.equal(empty.analysisFulfillmentReady, false);
  assert.equal(empty.paidCatalogFulfillmentReady, false);
  assert.equal(parsePaymentRuntime({ ...configuredTestRuntime, PAYMENTS_ENABLED: "TRUE" }).paymentsEnabled, false);
  assert.equal(parsePaymentRuntime({ ...configuredTestRuntime, PAYMENT_MODE: "sandbox" }).paymentsEnabled, false);
});

test("checkout stays locked until paid catalog fulfillment is complete", async () => {
  const { parsePaymentRuntime } = await vite.ssrLoadModule(
    "/lib/payments/runtime-config.ts",
  );
  const ready = parsePaymentRuntime(configuredTestRuntime);
  assert.equal(ready.paymentsEnabled, false);
  assert.equal(ready.settlementEnabled, true);
  assert.equal(ready.paymentMode, "test");
  assert.equal(ready.analysisFulfillmentReady, true);
  assert.equal(ready.paidCatalogFulfillmentReady, false);

  const stopped = parsePaymentRuntime({
    ...configuredTestRuntime,
    PAYMENTS_ENABLED: "false",
  });
  assert.equal(stopped.paymentsEnabled, false);
  assert.equal(stopped.settlementEnabled, true);

  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    ANALYSIS_FULFILLMENT_ENABLED: "false",
  }).paymentsEnabled, false);

  for (const missing of ["OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_ALLOWED_MODELS", "DB"]) {
    const runtime = { ...configuredTestRuntime };
    delete runtime[missing];
    assert.equal(parsePaymentRuntime(runtime).paymentsEnabled, false, missing);
  }

  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    PAYMENT_SETTLEMENT_ENABLED: "false",
  }).paymentsEnabled, false);

  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    DB: {},
  }).analysisFulfillmentReady, false);
  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    DB: "not-a-binding",
  }).analysisFulfillmentReady, false);
});

test("settlement remains available when analysis dependencies are absent", async () => {
  const { parsePaymentRuntime } = await vite.ssrLoadModule(
    "/lib/payments/runtime-config.ts",
  );
  for (const missing of [
    "ANALYSIS_RUNTIME_ENABLED",
    "ANALYSIS_FULFILLMENT_ENABLED",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_ALLOWED_MODELS",
    "DB",
  ]) {
    const runtime = { ...configuredTestRuntime };
    delete runtime[missing];
    const parsed = parsePaymentRuntime(runtime);
    assert.equal(parsed.paymentsEnabled, false, missing);
    assert.equal(parsed.settlementEnabled, true, missing);
  }
});

test("test and live modes cannot reuse the other mode credentials", async () => {
  const { parsePaymentRuntime } = await vite.ssrLoadModule(
    "/lib/payments/runtime-config.ts",
  );
  const liveWithOnlyTestSecrets = parsePaymentRuntime({
    ...configuredTestRuntime,
    PAYMENT_MODE: "live",
  });
  assert.equal(liveWithOnlyTestSecrets.credentialsConfigured, false);
  assert.equal(liveWithOnlyTestSecrets.paymentsEnabled, false);
  assert.equal(liveWithOnlyTestSecrets.settlementEnabled, false);
});

test("checkout rejects a non-canonical or non-HTTPS app origin", async () => {
  const { parsePaymentRuntime } = await vite.ssrLoadModule(
    "/lib/payments/runtime-config.ts",
  );
  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    APP_ORIGIN: "http://staging.example.test",
  }).paymentsEnabled, false);
  assert.equal(parsePaymentRuntime({
    ...configuredTestRuntime,
    APP_ORIGIN: "https://staging.example.test/checkout",
  }).paymentsEnabled, false);
});
