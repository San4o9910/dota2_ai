import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { DatabaseSync } from "node:sqlite";
import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const migrationPaths = [
  "../drizzle/0000_abandoned_stone_men.sql",
  "../drizzle/0001_billing_foundation.sql",
  "../drizzle/0002_ledger_resolution_guards.sql",
  "../drizzle/0003_dota_player_slot_guard.sql",
  "../drizzle/0004_entitlement_bucket_uniqueness.sql",
  "../drizzle/0005_block_unsettled_coach_orders.sql",
  "../drizzle/0006_brainy_falcon.sql",
  "../drizzle/0007_special_ben_grimm.sql",
];
const migrations = await Promise.all(
  migrationPaths.map((path) => readFile(new URL(path, import.meta.url), "utf8")),
);
const routeMocksKey = "__PAYMENT_HARDENING_ROUTE_MOCKS__";
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  plugins: [{
    name: "payment-hardening-route-mocks",
    enforce: "pre",
    resolveId(source) {
      if (["@/db", `${root}/db`, `${root}/db/index.ts`].includes(source)) {
        return "\0payment-hardening-db";
      }
      if ([
        "@/app/chatgpt-auth",
        `${root}/app/chatgpt-auth`,
        `${root}/app/chatgpt-auth.ts`,
      ].includes(source)) {
        return "\0payment-hardening-auth";
      }
      if ([
        "@/lib/auth/current-account",
        `${root}/lib/auth/current-account`,
        `${root}/lib/auth/current-account.ts`,
      ].includes(source)) {
        return "\0payment-hardening-account";
      }
      if ([
        "@/lib/payments/runtime",
        `${root}/lib/payments/runtime`,
        `${root}/lib/payments/runtime.ts`,
      ].includes(source)) {
        return "\0payment-hardening-runtime";
      }
      if ([
        "@/lib/payments/yookassa",
        `${root}/lib/payments/yookassa`,
        `${root}/lib/payments/yookassa.ts`,
      ].includes(source)) {
        return "\0payment-hardening-yookassa";
      }
      return null;
    },
    load(id) {
      if (id === "\0payment-hardening-db") {
        return `export function getDb() {
          return globalThis.${routeMocksKey}.db;
        }`;
      }
      if (id === "\0payment-hardening-auth") {
        return `export async function getChatGPTUser() {
          return globalThis.${routeMocksKey}.user;
        }`;
      }
      if (id === "\0payment-hardening-account") {
        return `export async function getOrCreateCurrentAccount() {
          return globalThis.${routeMocksKey}.account;
        }`;
      }
      if (id === "\0payment-hardening-runtime") {
        return `
          export function paymentsEnabled() { return true; }
          export function paymentSettlementEnabled() { return true; }
          export function getPaymentRuntimeIdentity() {
            return globalThis.${routeMocksKey}.runtimeIdentity;
          }
          export function getPaymentSettlementIdentity() {
            return globalThis.${routeMocksKey}.runtimeIdentity;
          }
          export function getYooKassaCredentials() { return {}; }
        `;
      }
      if (id === "\0payment-hardening-yookassa") {
        return `
          export class YooKassaError extends Error {}
          export async function getYooKassaPayment() {
            const mocks = globalThis.${routeMocksKey};
            mocks.providerCalls += 1;
            await mocks.onProviderRead?.();
            return mocks.payment;
          }
          export async function createCheckoutPayment() {
            const mocks = globalThis.${routeMocksKey};
            mocks.providerCalls += 1;
            await mocks.onProviderRead?.();
            return mocks.payment;
          }
          export function paymentMatchesMode(payment, mode) {
            return payment.test === (mode === "test");
          }
          export function checkoutPaymentMatchesOrder(payment, expected, mode) {
            return paymentMatchesMode(payment, mode)
              && payment.amount.currency === "RUB"
              && payment.amount.value === expected.amountRub
              && payment.metadata?.order_id === expected.orderId
              && payment.metadata?.product_code === expected.productCode
              && payment.metadata?.match_id === expected.matchId;
          }
          export function isConfirmedCheckoutPayment(payment, expected, mode) {
            return payment.status === "succeeded"
              && payment.paid === true
              && checkoutPaymentMatchesOrder(payment, expected, mode);
          }
        `;
      }
      return null;
    },
  }],
  server: { middlewareMode: true, hmr: false },
});

after(async () => {
  await vite.close();
  delete globalThis[routeMocksKey];
});

function statements(source) {
  return source
    .split("--> statement-breakpoint")
    .map((statement) => statement.trim())
    .filter(Boolean);
}

function applyMigration(db, source) {
  db.exec("BEGIN");
  try {
    for (const statement of statements(source)) db.exec(statement);
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

function migratedDatabase({ through = migrations.length } = {}) {
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  for (const migration of migrations.slice(0, through)) applyMigration(db, migration);
  return db;
}

function insertUser(db, id = "user-1") {
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run(id, `Tester ${id}`);
}

function insertOrder(db, overrides = {}) {
  const order = {
    id: "order-1",
    userId: "user-1",
    productCode: "single_analysis",
    productVersion: "single-analysis.v1",
    checkoutAttemptId: "attempt-1",
    requestHash: "request-hash-1",
    providerIdempotencyKey: "order-1",
    matchId: "8963624400",
    amountKopecks: 29_900,
    currency: "RUB",
    grantAnalyses: 1,
    grantCoachQuestions: 10,
    durationDays: null,
    environment: "production",
    paymentMode: "live",
    provider: "yookassa",
    providerShopId: "shop-1",
    providerTest: null,
    status: "created",
    fulfillmentStatus: "not_granted",
    refundStatus: "none",
    yookassaPaymentId: null,
    creditedAt: null,
    createdAt: "2026-09-04 00:00:00",
    updatedAt: "2026-09-04 00:00:00",
    ...overrides,
  };

  db.prepare(`
    INSERT INTO orders (
      id, user_id, product_code, product_version, checkout_attempt_id,
      request_hash, provider_idempotency_key, match_id, amount_kopecks,
      currency, grant_analyses, grant_coach_questions, duration_days,
      environment, payment_mode, provider, provider_shop_id, provider_test,
      status, fulfillment_status, refund_status, yookassa_payment_id,
      credited_at, created_at, updated_at
    ) VALUES (
      ?, ?, ?, ?, ?,
      ?, ?, ?, ?,
      ?, ?, ?, ?,
      ?, ?, ?, ?, ?,
      ?, ?, ?, ?,
      ?, ?, ?
    )
  `).run(
    order.id,
    order.userId,
    order.productCode,
    order.productVersion,
    order.checkoutAttemptId,
    order.requestHash,
    order.providerIdempotencyKey,
    order.matchId,
    order.amountKopecks,
    order.currency,
    order.grantAnalyses,
    order.grantCoachQuestions,
    order.durationDays,
    order.environment,
    order.paymentMode,
    order.provider,
    order.providerShopId,
    order.providerTest,
    order.status,
    order.fulfillmentStatus,
    order.refundStatus,
    order.yookassaPaymentId,
    order.creditedAt,
    order.createdAt,
    order.updatedAt,
  );
  return order;
}

function mockedWebhookDb(order) {
  const state = { batches: [], runCalls: 0 };
  return {
    state,
    db: {
      select() {
        return {
          from() {
            return {
              where() {
                return { limit: async () => [order] };
              },
            };
          },
        };
      },
      insert() {
        return {
          values(values) {
            return {
              onConflictDoNothing() {
                return { kind: "insert-provider-event", values };
              },
            };
          },
        };
      },
      update() {
        return {
          set(values) {
            return {
              where() {
                return { kind: "update-order", values };
              },
            };
          },
        };
      },
      run() {
        state.runCalls += 1;
        return { kind: "raw-update" };
      },
      async batch(statements) {
        state.batches.push(statements);
      },
    },
  };
}

function mockedCheckoutDb(initialOrder, persistedOrder) {
  let selection = 0;
  const state = { rawUpdates: 0, staleUpdates: 0 };
  return {
    state,
    db: {
      select() {
        return {
          from() {
            return {
              where() {
                return {
                  async limit() {
                    selection += 1;
                    return [{ ...(selection === 1 ? initialOrder : persistedOrder) }];
                  },
                };
              },
            };
          },
        };
      },
      run() {
        state.rawUpdates += 1;
        return { changes: 1 };
      },
      update() {
        return {
          set(values) {
            return {
              where() {
                state.staleUpdates += 1;
                Object.assign(persistedOrder, values);
                return { changes: 1 };
              },
            };
          },
        };
      },
    },
  };
}

async function webhookOrder(overrides = {}) {
  const { billingRequestHash } = await vite.ssrLoadModule(
    "/lib/billing/order-idempotency.ts",
  );
  const order = {
    id: "9b2cd389-4cc0-4937-87a0-16181d7eff83",
    userId: "user-1",
    checkoutAttemptId: "attempt-1",
    productCode: "single_analysis",
    productVersion: "single-analysis.v1",
    matchId: "8963624400",
    amountKopecks: 29_900,
    currency: "RUB",
    grantAnalyses: 1,
    grantCoachQuestions: 10,
    durationDays: null,
    environment: "production",
    paymentMode: "test",
    provider: "yookassa",
    providerShopId: "shop-1",
    providerIdempotencyKey: "9b2cd389-4cc0-4937-87a0-16181d7eff83",
    providerTest: true,
    yookassaPaymentId: "payment-canonical-1",
    paymentStatus: "pending",
    fulfillmentStatus: "not_granted",
    creditedAt: null,
    ...overrides,
  };
  order.requestHash = await billingRequestHash({
    orderId: order.id,
    userId: order.userId,
    checkoutAttemptId: order.checkoutAttemptId,
    productCode: order.productCode,
    productVersion: order.productVersion,
    matchId: order.matchId,
    amountKopecks: order.amountKopecks,
    currency: order.currency,
    grantAnalyses: order.grantAnalyses,
    grantCoachQuestions: order.grantCoachQuestions,
    durationDays: order.durationDays,
    environment: order.environment,
    paymentMode: order.paymentMode,
    provider: order.provider,
    providerShopId: order.providerShopId,
    providerIdempotencyKey: order.providerIdempotencyKey,
  });
  return order;
}

test("billing integrity hashes every order, grant, duration, and provider identity field", async () => {
  const {
    BILLING_ORDER_INTEGRITY_VERSION,
    billingRequestHash,
    serializeBillingRequest,
  } = await vite.ssrLoadModule("/lib/billing/order-idempotency.ts");
  const identity = {
    orderId: "9b2cd389-4cc0-4937-87a0-16181d7eff83",
    userId: "user-1",
    checkoutAttemptId: "attempt-1",
    productCode: "single_analysis",
    productVersion: "single-analysis.v1",
    matchId: "8963624400",
    amountKopecks: 29_900,
    currency: "RUB",
    grantAnalyses: 1,
    grantCoachQuestions: 10,
    durationDays: null,
    environment: "production",
    paymentMode: "live",
    provider: "yookassa",
    providerShopId: "shop-1",
    providerIdempotencyKey: "9b2cd389-4cc0-4937-87a0-16181d7eff83",
  };
  const serialized = JSON.parse(serializeBillingRequest(identity));
  assert.equal(serialized.integrityVersion, BILLING_ORDER_INTEGRITY_VERSION);
  assert.deepEqual(serialized, {
    integrityVersion: "billing-order-integrity.v1",
    ...identity,
  });

  const baseline = await billingRequestHash(identity);
  assert.match(baseline, /^[a-f0-9]{64}$/);
  const mutations = {
    orderId: "22b36fd8-d4fb-448b-a7c2-b53a69c54188",
    userId: "user-2",
    checkoutAttemptId: "attempt-2",
    productCode: "coach_30_days",
    productVersion: "coach.v2",
    matchId: "8963624401",
    amountKopecks: 79_900,
    currency: "USD",
    grantAnalyses: 8,
    grantCoachQuestions: 40,
    durationDays: 30,
    environment: "staging",
    paymentMode: "test",
    provider: "another-provider",
    providerShopId: "shop-2",
    providerIdempotencyKey: "provider-key-2",
  };

  for (const [field, value] of Object.entries(mutations)) {
    assert.notEqual(
      await billingRequestHash({ ...identity, [field]: value }),
      baseline,
      `${field} must participate in the integrity hash`,
    );
  }
});

test("migrations 0000 through 0007 apply atomically with the hardening objects", () => {
  const db = migratedDatabase();
  assert.deepEqual(db.prepare("PRAGMA foreign_key_check").all(), []);

  const indexColumns = db.prepare("PRAGMA index_info('provider_events_transition_unique')")
    .all()
    .map((row) => row.name);
  assert.deepEqual(indexColumns, ["provider", "event_type", "provider_payment_id"]);
  assert.equal(
    db.prepare(`
      SELECT COUNT(*) AS total FROM sqlite_master
      WHERE type = 'index' AND name = 'provider_events_delivery_unique'
    `).get().total,
    0,
  );

  const triggers = db.prepare(`
    SELECT name FROM sqlite_master
    WHERE type = 'trigger' AND name LIKE 'orders_%'
    ORDER BY name
  `).all().map((row) => row.name);
  assert.deepEqual(triggers, [
    "orders_lifecycle_monotonic_update",
    "orders_snapshot_immutable_update",
  ]);
  db.close();
});

test("migration 0007 preserves existing jobs and permits only terminal identity reuse", () => {
  const db = migratedDatabase({ through: 7 });
  insertUser(db, "analysis-upgrade-user");
  const insertJob = db.prepare(`
    INSERT INTO analysis_jobs (
      id, user_id, match_id, player_slot, report_version,
      state, idempotency_key, request_hash
    ) VALUES (?, 'analysis-upgrade-user', ?, ?, 'analysis-report.v1', ?, ?, ?)
  `);
  insertJob.run(
    "terminal-before-upgrade",
    "8963624400",
    0,
    "failed",
    "terminal-before-upgrade",
    "terminal-hash",
  );
  insertJob.run(
    "active-before-upgrade",
    "8963624401",
    1,
    "running",
    "active-before-upgrade",
    "active-hash",
  );

  applyMigration(db, migrations[7]);
  const existing = db.prepare(`
    SELECT id, state, retry_not_before
    FROM analysis_jobs
    ORDER BY id
  `).all().map((row) => ({ ...row }));
  assert.deepEqual(existing, [
    { id: "active-before-upgrade", state: "running", retry_not_before: null },
    { id: "terminal-before-upgrade", state: "failed", retry_not_before: null },
  ]);

  insertJob.run(
    "fresh-after-terminal",
    "8963624400",
    0,
    "queued",
    "fresh-after-terminal",
    "fresh-hash",
  );
  assert.throws(() => insertJob.run(
    "duplicate-active",
    "8963624401",
    1,
    "queued",
    "duplicate-active",
    "duplicate-hash",
  ), /UNIQUE constraint failed/);
  assert.equal(
    db.prepare(`
      SELECT COUNT(*) AS total FROM sqlite_master
      WHERE type = 'index' AND name = 'analysis_jobs_report_identity_unique'
    `).get().total,
    0,
  );
  db.close();
});

test("migration 0006 fails closed when historical semantic event duplicates exist", () => {
  const db = migratedDatabase({ through: 6 });
  db.prepare(`
    INSERT INTO provider_events (
      id, provider, event_type, provider_payment_id, payload_hash,
      payment_mode, provider_test
    ) VALUES (?, 'yookassa', 'payment.succeeded', 'payment-duplicate', ?, 'live', 0)
  `).run("event-a", "payload-a");
  db.prepare(`
    INSERT INTO provider_events (
      id, provider, event_type, provider_payment_id, payload_hash,
      payment_mode, provider_test
    ) VALUES (?, 'yookassa', 'payment.succeeded', 'payment-duplicate', ?, 'live', 0)
  `).run("event-b", "payload-b");

  assert.throws(
    () => applyMigration(db, migrations[6]),
    /UNIQUE constraint failed: provider_events\.provider, provider_events\.event_type, provider_events\.provider_payment_id/,
  );
  assert.equal(
    db.prepare(`
      SELECT COUNT(*) AS total FROM sqlite_master
      WHERE type = 'index' AND name = 'provider_events_delivery_unique'
    `).get().total,
    1,
    "the previous guard must survive a rolled-back migration",
  );
  db.close();
});

test("every protected commercial order snapshot column is immutable", () => {
  const db = migratedDatabase();
  insertUser(db);
  insertUser(db, "user-2");
  insertOrder(db);

  const mutations = {
    id: "order-mutated",
    user_id: "user-2",
    product_code: "coach_30_days",
    product_version: "product-v2",
    checkout_attempt_id: "attempt-mutated",
    request_hash: "request-hash-mutated",
    provider_idempotency_key: "provider-key-mutated",
    match_id: "8963624401",
    amount_kopecks: 79_900,
    currency: "USD",
    grant_analyses: 999,
    grant_coach_questions: 999,
    duration_days: 30,
    environment: "staging",
    payment_mode: "test",
    provider: "other-provider",
    provider_shop_id: "shop-2",
    created_at: "2026-09-05 00:00:00",
  };

  for (const [column, value] of Object.entries(mutations)) {
    assert.throws(
      () => db.prepare(`UPDATE orders SET ${column} = ? WHERE id = 'order-1'`).run(value),
      /order snapshot is immutable/,
      `${column} must be immutable`,
    );
  }
  const snapshot = db.prepare(`
    SELECT id, user_id, amount_kopecks, grant_analyses, grant_coach_questions,
           duration_days, provider, provider_shop_id
    FROM orders WHERE id = 'order-1'
  `).get();
  assert.deepEqual({ ...snapshot }, {
    id: "order-1",
    user_id: "user-1",
    amount_kopecks: 29_900,
    grant_analyses: 1,
    grant_coach_questions: 10,
    duration_days: null,
    provider: "yookassa",
    provider_shop_id: "shop-1",
  });
  db.close();
});

test("order ownership cannot be detached directly but ON DELETE SET NULL remains valid", () => {
  const db = migratedDatabase();
  insertUser(db);
  insertOrder(db);

  assert.throws(
    () => db.prepare("UPDATE orders SET user_id = NULL WHERE id = 'order-1'").run(),
    /order snapshot is immutable/,
  );
  assert.equal(
    db.prepare("SELECT user_id FROM orders WHERE id = 'order-1'").get().user_id,
    "user-1",
  );

  db.prepare("DELETE FROM users WHERE id = 'user-1'").run();
  assert.equal(
    db.prepare("SELECT user_id FROM orders WHERE id = 'order-1'").get().user_id,
    null,
  );
  assert.deepEqual(db.prepare("PRAGMA foreign_key_check").all(), []);
  db.close();
});

test("provider bindings, credit evidence, and terminal outcomes only move forward", () => {
  const db = migratedDatabase();
  insertUser(db);

  insertOrder(db, { id: "binding-order", checkoutAttemptId: "binding-attempt", providerIdempotencyKey: "binding-order" });
  db.prepare(`
    UPDATE orders SET yookassa_payment_id = 'payment-1', provider_test = 1
    WHERE id = 'binding-order'
  `).run();
  db.prepare(`
    UPDATE orders SET yookassa_payment_id = 'payment-1', provider_test = 1
    WHERE id = 'binding-order'
  `).run();
  assert.throws(
    () => db.prepare("UPDATE orders SET yookassa_payment_id = 'payment-2' WHERE id = 'binding-order'").run(),
    /order lifecycle cannot regress/,
  );
  assert.throws(
    () => db.prepare("UPDATE orders SET yookassa_payment_id = NULL WHERE id = 'binding-order'").run(),
    /order lifecycle cannot regress/,
  );
  assert.throws(
    () => db.prepare("UPDATE orders SET provider_test = 0 WHERE id = 'binding-order'").run(),
    /order lifecycle cannot regress/,
  );
  assert.throws(
    () => db.prepare("UPDATE orders SET provider_test = NULL WHERE id = 'binding-order'").run(),
    /order lifecycle cannot regress/,
  );

  insertOrder(db, { id: "credit-order", checkoutAttemptId: "credit-attempt", providerIdempotencyKey: "credit-order" });
  db.prepare("UPDATE orders SET credited_at = '2026-09-04 01:00:00' WHERE id = 'credit-order'").run();
  db.prepare("UPDATE orders SET credited_at = '2026-09-04 01:00:00' WHERE id = 'credit-order'").run();
  assert.throws(
    () => db.prepare("UPDATE orders SET credited_at = NULL WHERE id = 'credit-order'").run(),
    /order lifecycle cannot regress/,
  );
  assert.throws(
    () => db.prepare("UPDATE orders SET credited_at = '2026-09-04 02:00:00' WHERE id = 'credit-order'").run(),
    /order lifecycle cannot regress/,
  );

  insertOrder(db, { id: "success-order", checkoutAttemptId: "success-attempt", providerIdempotencyKey: "success-order", status: "pending" });
  db.prepare("UPDATE orders SET status = 'succeeded' WHERE id = 'success-order'").run();
  db.prepare("UPDATE orders SET status = 'succeeded' WHERE id = 'success-order'").run();
  assert.throws(
    () => db.prepare("UPDATE orders SET status = 'pending' WHERE id = 'success-order'").run(),
    /order lifecycle cannot regress/,
  );
  assert.throws(
    () => db.prepare("UPDATE orders SET status = 'canceled' WHERE id = 'success-order'").run(),
    /order lifecycle cannot regress/,
  );

  insertOrder(db, { id: "capture-order", checkoutAttemptId: "capture-attempt", providerIdempotencyKey: "capture-order", status: "waiting_for_capture" });
  assert.throws(
    () => db.prepare("UPDATE orders SET status = 'pending' WHERE id = 'capture-order'").run(),
    /order lifecycle cannot regress/,
  );

  insertOrder(db, { id: "canceled-order", checkoutAttemptId: "canceled-attempt", providerIdempotencyKey: "canceled-order", status: "canceled" });
  assert.throws(
    () => db.prepare("UPDATE orders SET status = 'pending' WHERE id = 'canceled-order'").run(),
    /order lifecycle cannot regress/,
  );

  insertOrder(db, { id: "review-order", checkoutAttemptId: "review-attempt", providerIdempotencyKey: "review-order" });
  db.prepare("UPDATE orders SET fulfillment_status = 'manual_review' WHERE id = 'review-order'").run();
  assert.throws(
    () => db.prepare("UPDATE orders SET fulfillment_status = 'not_granted' WHERE id = 'review-order'").run(),
    /order lifecycle cannot regress/,
  );
  db.prepare("UPDATE orders SET fulfillment_status = 'granted' WHERE id = 'review-order'").run();
  assert.throws(
    () => db.prepare("UPDATE orders SET fulfillment_status = 'manual_review' WHERE id = 'review-order'").run(),
    /order lifecycle cannot regress/,
  );
  db.close();
});

test("canonical provider transitions are unique across notification payload variants", () => {
  const db = migratedDatabase();
  const insertEvent = db.prepare(`
    INSERT INTO provider_events (
      id, provider, event_type, provider_payment_id, payload_hash,
      payment_mode, provider_test
    ) VALUES (?, 'yookassa', ?, 'payment-1', ?, 'live', 0)
  `);
  insertEvent.run("event-1", "payment.succeeded", "payload-hash-a");
  assert.throws(
    () => insertEvent.run("event-2", "payment.succeeded", "payload-hash-b"),
    /UNIQUE constraint failed: provider_events\.provider, provider_events\.event_type, provider_events\.provider_payment_id/,
  );
  insertEvent.run("event-3", "payment.canceled", "payload-hash-c");

  const transitions = db.prepare(`
    SELECT event_type, payload_hash FROM provider_events
    WHERE provider_payment_id = 'payment-1' ORDER BY event_type
  `).all().map((row) => ({ ...row }));
  assert.deepEqual(transitions, [
    { event_type: "payment.canceled", payload_hash: "payload-hash-c" },
    { event_type: "payment.succeeded", payload_hash: "payload-hash-a" },
  ]);
  db.close();
});

test("a stale checkout CAS cannot overwrite webhook success, grant, or credit evidence", () => {
  const db = migratedDatabase();
  insertUser(db);
  insertOrder(db, {
    id: "settled-order",
    checkoutAttemptId: "settled-attempt",
    providerIdempotencyKey: "settled-order",
    providerTest: 0,
    status: "succeeded",
    fulfillmentStatus: "granted",
    yookassaPaymentId: "payment-settled",
    creditedAt: "2026-09-04 01:00:00",
  });

  const staleCheckoutUpdate = db.prepare(`
    UPDATE orders
    SET yookassa_payment_id = COALESCE(yookassa_payment_id, ?),
        provider_test = COALESCE(provider_test, ?),
        status = CASE
          WHEN status IN ('succeeded', 'canceled') OR credited_at IS NOT NULL
            THEN status
          WHEN status = 'waiting_for_capture' AND ? = 'pending'
            THEN status
          ELSE ?
        END,
        fulfillment_status = CASE
          WHEN fulfillment_status = 'granted' OR credited_at IS NOT NULL
            THEN fulfillment_status
          WHEN ? = 1 THEN 'manual_review'
          ELSE fulfillment_status
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
      AND (yookassa_payment_id IS NULL OR yookassa_payment_id = ?)
      AND (provider_test IS NULL OR provider_test = ?)
  `);

  const applied = staleCheckoutUpdate.run(
    "payment-settled",
    0,
    "pending",
    "pending",
    1,
    "settled-order",
    "payment-settled",
    0,
  );
  assert.equal(applied.changes, 1);
  assert.deepEqual({ ...db.prepare(`
    SELECT yookassa_payment_id, provider_test, status,
           fulfillment_status, credited_at
    FROM orders WHERE id = 'settled-order'
  `).get() }, {
    yookassa_payment_id: "payment-settled",
    provider_test: 0,
    status: "succeeded",
    fulfillment_status: "granted",
    credited_at: "2026-09-04 01:00:00",
  });

  const rejectedRebind = staleCheckoutUpdate.run(
    "payment-other",
    1,
    "pending",
    "pending",
    1,
    "settled-order",
    "payment-other",
    1,
  );
  assert.equal(rejectedRebind.changes, 0);
  assert.equal(
    db.prepare("SELECT yookassa_payment_id FROM orders WHERE id = 'settled-order'").get()
      .yookassa_payment_id,
    "payment-settled",
  );
  db.close();
});

test("checkout handler rereads CAS state after a webhook wins the race", async () => {
  const checkoutAttemptId = "3a30cb3e-aef2-4f06-a50b-8882635ac202";
  const initialOrder = await webhookOrder({
    checkoutAttemptId,
    productVersion: "closed-beta-2026-09-v1",
  });
  const persistedOrder = { ...initialOrder };
  const { db, state } = mockedCheckoutDb(initialOrder, persistedOrder);
  globalThis[routeMocksKey] = {
    db,
    user: {
      id: "chatgpt-user-1",
      email: "tester@example.test",
      displayName: "Tester",
      fullName: "Tester",
    },
    account: {
      id: "user-1",
      status: "active",
      planCode: "free_trial",
    },
    runtimeIdentity: {
      environment: "production",
      paymentMode: "test",
      providerShopId: "shop-1",
      appOrigin: "https://example.test",
    },
    providerCalls: 0,
    async onProviderRead() {
      persistedOrder.paymentStatus = "succeeded";
      persistedOrder.fulfillmentStatus = "granted";
      persistedOrder.creditedAt = "2026-09-04 01:00:00";
    },
    payment: {
      id: "payment-canonical-1",
      status: "pending",
      paid: false,
      test: true,
      amount: { value: "299.00", currency: "RUB" },
      confirmation: {
        type: "redirect",
        confirmation_url: "https://provider.example.test/checkout",
      },
      metadata: {
        order_id: initialOrder.id,
        product_code: initialOrder.productCode,
        match_id: initialOrder.matchId,
      },
    },
  };

  const { POST } = await vite.ssrLoadModule("/app/api/payments/create/route.ts");
  const response = await POST(new Request("https://example.test/api/payments/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Origin: "https://example.test",
    },
    body: JSON.stringify({
      checkoutAttemptId,
      productCode: "single_analysis",
      matchId: initialOrder.matchId,
    }),
  }));

  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), {
    error: "Этот заказ уже оплачен. Проверьте лимиты в аккаунте.",
  });
  assert.equal(globalThis[routeMocksKey].providerCalls, 1);
  assert.equal(state.rawUpdates, 1);
  assert.equal(state.staleUpdates, 0);
  assert.equal(persistedOrder.paymentStatus, "succeeded");
  assert.equal(persistedOrder.fulfillmentStatus, "granted");
  assert.equal(persistedOrder.creditedAt, "2026-09-04 01:00:00");
});

test("webhook persists the authoritative provider transition, not the claimed event", async () => {
  const order = await webhookOrder();
  const { db, state } = mockedWebhookDb(order);
  globalThis[routeMocksKey] = {
    db,
    runtimeIdentity: {
      environment: "production",
      paymentMode: "test",
      providerShopId: "shop-1",
    },
    providerCalls: 0,
    payment: {
      id: "payment-canonical-1",
      status: "canceled",
      paid: false,
      test: true,
      amount: { value: "299.00", currency: "RUB" },
      metadata: { order_id: order.id, product_code: order.productCode, match_id: order.matchId },
    },
  };

  const { POST } = await vite.ssrLoadModule("/app/api/payments/webhook/route.ts");
  const response = await POST(new Request("https://example.test/api/payments/webhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event: "payment.succeeded",
      object: { id: "payment-canonical-1" },
    }),
  }));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { accepted: true });
  assert.equal(globalThis[routeMocksKey].providerCalls, 1);
  assert.equal(state.batches.length, 1);
  assert.equal(state.batches[0][0].kind, "insert-provider-event");
  assert.equal(state.batches[0][0].values.eventType, "payment.canceled");
  assert.equal(state.batches[0][0].values.providerPaymentId, "payment-canonical-1");
  assert.match(state.batches[0][0].values.payloadHash, /^[a-f0-9]{64}$/);
});

test("webhook rejects a legacy or corrupted integrity hash before provider access", async () => {
  const order = await webhookOrder({ requestHash: "legacy-request-hash" });
  order.requestHash = "legacy-request-hash";
  const { db, state } = mockedWebhookDb(order);
  globalThis[routeMocksKey] = {
    db,
    runtimeIdentity: {
      environment: "production",
      paymentMode: "test",
      providerShopId: "shop-1",
    },
    providerCalls: 0,
    payment: null,
  };

  const { POST } = await vite.ssrLoadModule("/app/api/payments/webhook/route.ts");
  const response = await POST(new Request("https://example.test/api/payments/webhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event: "payment.succeeded",
      object: { id: "payment-canonical-1" },
    }),
  }));

  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: "Order integrity check failed" });
  assert.equal(globalThis[routeMocksKey].providerCalls, 0);
  assert.equal(state.runCalls, 1);
  assert.equal(state.batches.length, 0);
});
