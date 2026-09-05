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

  assert.equal(isConfirmedAnalysisPayment(payment, request, "live"), true);
  assert.equal(isConfirmedAnalysisPayment(payment, request, "test"), false);
  assert.equal(isConfirmedAnalysisPayment({ ...payment, amount: { value: "1.00", currency: "RUB" } }, request, "live"), false);
  assert.equal(isConfirmedAnalysisPayment({ ...payment, status: "pending" }, request, "live"), false);
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
  const {
    checkoutPaymentMatchesOrder,
    createCheckoutPayment,
    isConfirmedCheckoutPayment,
  } = await vite.ssrLoadModule(
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
  assert.equal(checkoutPaymentMatchesOrder(payment, checkout, "test"), true);
  assert.equal(isConfirmedCheckoutPayment(payment, checkout, "test"), true);
  assert.equal(isConfirmedCheckoutPayment(payment, checkout, "live"), false);
  assert.equal(isConfirmedCheckoutPayment({ ...payment, amount: { value: "1.00", currency: "RUB" } }, checkout, "test"), false);
  assert.equal(checkoutPaymentMatchesOrder({
    ...payment,
    metadata: { ...payment.metadata, match_id: "8963624400" },
  }, checkout, "test"), false);
  assert.equal(checkoutPaymentMatchesOrder({
    ...payment,
    status: "pending",
    paid: false,
  }, checkout, "test"), true);
});

test("rejects malformed, non-JSON and oversized provider responses", async () => {
  const { createAnalysisPayment } = await vite.ssrLoadModule("/lib/payments/yookassa.ts");

  await assert.rejects(
    createAnalysisPayment(credentials, request, async () => Response.json({
      id: "2f63c820-000f-5000-9000-1b68e2b15f29",
      status: "pending",
      amount: { value: "499.00", currency: "RUB" },
    })),
    /invalid payment fields/,
  );

  await assert.rejects(
    createAnalysisPayment(credentials, request, async () => new Response("gateway error", {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    })),
    /non-JSON response/,
  );

  await assert.rejects(
    createAnalysisPayment(credentials, request, async () => new Response("{}", {
      headers: { "Content-Type": "application/jsonp" },
    })),
    /non-JSON response/,
  );

  await assert.rejects(
    createAnalysisPayment(credentials, request, async () => new Response(
      JSON.stringify({ filler: "x".repeat(70_000) }),
      { headers: { "Content-Type": "application/json" } },
    )),
    /size limit/,
  );
});

test("normalizes transport timeouts without exposing fetch internals", async () => {
  const { createAnalysisPayment, YooKassaError } = await vite.ssrLoadModule(
    "/lib/payments/yookassa.ts",
  );
  const timeout = new Error("socket 10.0.0.1 timed out");
  timeout.name = "TimeoutError";
  await assert.rejects(
    createAnalysisPayment(credentials, request, async () => { throw timeout; }),
    (error) => error instanceof YooKassaError
      && error.message === "YooKassa request timed out"
      && error.status === undefined,
  );
});

test("maps provider authentication and balance statuses to dependency 503", async () => {
  const { YooKassaError } = await vite.ssrLoadModule("/lib/payments/yookassa.ts");
  const { paymentRouteFailure } = await vite.ssrLoadModule(
    "/lib/payments/route-error.ts",
  );
  assert.deepEqual(paymentRouteFailure(new YooKassaError("provider auth", 401)), {
    status: 503,
    code: "PAYMENT_PROVIDER_UNAVAILABLE",
  });
  assert.deepEqual(paymentRouteFailure(new YooKassaError("provider balance", 402)), {
    status: 503,
    code: "PAYMENT_PROVIDER_UNAVAILABLE",
  });
  assert.deepEqual(paymentRouteFailure(new Error("D1 unavailable")), {
    status: 500,
    code: "PAYMENT_STORAGE_UNAVAILABLE",
  });
});
