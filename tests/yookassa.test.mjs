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

const credentials = {
  shopId: "123456",
  secretKey: "test_secret_key_123456",
};

const request = {
  orderId: "54e86508-e78b-4ff6-b3db-4116930b5027",
  matchId: "8963624400",
  amountRub: "499.00",
  returnUrl: "https://example.test/payment/return",
};

test("creates a server-side YooKassa request with stable idempotency", async () => {
  const { createAnalysisPayment } = await vite.ssrLoadModule("/lib/payments/yookassa.ts");
  let captured;
  const transport = async (url, init) => {
    captured = { url, init };
    return Response.json({
      id: "2f63c820-000f-5000-9000-1b68e2b15f29",
      status: "pending",
      paid: false,
      test: true,
      amount: { value: "499.00", currency: "RUB" },
      confirmation: { type: "redirect", confirmation_url: "https://yoomoney.ru/checkout/test" },
      metadata: { order_id: request.orderId, match_id: request.matchId, product: "match_analysis" },
    });
  };

  const payment = await createAnalysisPayment(credentials, request, transport);
  const body = JSON.parse(captured.init.body);

  assert.equal(captured.url, "https://api.yookassa.ru/v3/payments");
  assert.equal(captured.init.method, "POST");
  assert.equal(captured.init.headers["Idempotence-Key"], request.orderId);
  assert.match(captured.init.headers.Authorization, /^Basic /);
  assert.equal(body.amount.value, "499.00");
  assert.equal(body.amount.currency, "RUB");
  assert.equal(body.metadata.match_id, request.matchId);
  assert.equal(body.confirmation.return_url, request.returnUrl);
  assert.equal(payment.status, "pending");
});

test("confirms access only from a matching succeeded payment", async () => {
  const { isConfirmedAnalysisPayment } = await vite.ssrLoadModule("/lib/payments/yookassa.ts");
  const payment = {
    id: "2f63c820-000f-5000-9000-1b68e2b15f29",
    status: "succeeded",
    paid: true,
    test: false,
    amount: { value: request.amountRub, currency: "RUB" },
    metadata: { order_id: request.orderId, match_id: request.matchId, product: "match_analysis" },
  };

  assert.equal(isConfirmedAnalysisPayment(payment, request), true);
  assert.equal(isConfirmedAnalysisPayment({ ...payment, amount: { value: "1.00", currency: "RUB" } }, request), false);
  assert.equal(isConfirmedAnalysisPayment({ ...payment, status: "pending" }, request), false);
});

test("rejects invalid payment fields before networking", async () => {
  const { createAnalysisPayment } = await vite.ssrLoadModule("/lib/payments/yookassa.ts");
  let called = false;
  const transport = async () => {
    called = true;
    return Response.json({});
  };

  await assert.rejects(
    createAnalysisPayment(credentials, { ...request, amountRub: "0.00" }, transport),
    /positive RUB amount/,
  );
  await assert.rejects(
    createAnalysisPayment(credentials, { ...request, returnUrl: "http://example.test" }, transport),
    /HTTPS/,
  );
  assert.equal(called, false);
});

test("creates and verifies a catalog checkout without trusting a browser price", async () => {
  const { createCheckoutPayment, isConfirmedCheckoutPayment } = await vite.ssrLoadModule(
    "/lib/payments/yookassa.ts",
  );
  const checkout = {
    orderId: request.orderId,
    productCode: "coach_30_days",
    description: "NARMA VISION — AI-тренер на 30 дней",
    amountRub: "799.00",
    returnUrl: request.returnUrl,
  };
  let body;
  const payment = await createCheckoutPayment(credentials, checkout, async (_url, init) => {
    body = JSON.parse(init.body);
    return Response.json({
      id: "2f63c820-000f-5000-9000-1b68e2b15f29",
      status: "succeeded",
      paid: true,
      test: true,
      amount: { value: checkout.amountRub, currency: "RUB" },
      confirmation: { type: "redirect", confirmation_url: "https://yoomoney.ru/checkout/test" },
      metadata: { order_id: checkout.orderId, product_code: checkout.productCode },
    });
  });

  assert.equal(body.metadata.product_code, "coach_30_days");
  assert.equal(body.amount.value, "799.00");
  assert.equal(isConfirmedCheckoutPayment(payment, checkout), true);
  assert.equal(isConfirmedCheckoutPayment({ ...payment, amount: { value: "1.00", currency: "RUB" } }, checkout), false);
});
