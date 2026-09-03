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

test("launch catalog keeps server-authoritative prices and bounded usage", async () => {
  const { BILLING_CATALOG, FREE_TRIAL, yookassaAmount } = await vite.ssrLoadModule(
    "/lib/billing/catalog.ts",
  );

  assert.equal(FREE_TRIAL.priceKopecks, 0);
  assert.equal(FREE_TRIAL.analyses, 1);
  assert.equal(BILLING_CATALOG.single_analysis.priceKopecks, 29_900);
  assert.equal(BILLING_CATALOG.single_analysis.analyses, 1);
  assert.equal(BILLING_CATALOG.coach_30_days.priceKopecks, 79_900);
  assert.equal(BILLING_CATALOG.coach_30_days.analyses, 8);
  assert.equal(BILLING_CATALOG.coach_30_days.durationDays, 30);
  assert.equal(yookassaAmount(29_900), "299.00");
});

test("catalog does not offer an unlimited analysis plan", async () => {
  const { BILLING_CATALOG } = await vite.ssrLoadModule("/lib/billing/catalog.ts");
  for (const product of Object.values(BILLING_CATALOG)) {
    assert.ok(Number.isSafeInteger(product.analyses));
    assert.ok(product.analyses > 0 && product.analyses <= 8);
  }
});

test("catalog rejects inherited object keys as product codes", async () => {
  const { isPaidProductCode } = await vite.ssrLoadModule("/lib/billing/catalog.ts");
  assert.equal(isPaidProductCode("toString"), false);
  assert.equal(isPaidProductCode("constructor"), false);
});
