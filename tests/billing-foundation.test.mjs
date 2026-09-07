import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { DatabaseSync } from "node:sqlite";
import { createServer } from "vite";

const rootUrl = new URL("..", import.meta.url);
const root = fileURLToPath(rootUrl);
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

after(async () => vite.close());

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

test("billing migration preserves legacy orders and backfills opening balances", async () => {
  const initial = await readFile(new URL("../drizzle/0000_abandoned_stone_men.sql", import.meta.url), "utf8");
  const foundation = await readFile(new URL("../drizzle/0001_billing_foundation.sql", import.meta.url), "utf8");
  const guards = await readFile(new URL("../drizzle/0002_ledger_resolution_guards.sql", import.meta.url), "utf8");
  const slotGuard = await readFile(new URL("../drizzle/0003_dota_player_slot_guard.sql", import.meta.url), "utf8");
  const bucketGuard = await readFile(new URL("../drizzle/0004_entitlement_bucket_uniqueness.sql", import.meta.url), "utf8");
  const unsettledCoachGuard = await readFile(new URL("../drizzle/0005_block_unsettled_coach_orders.sql", import.meta.url), "utf8");
  const paymentStateGuards = await readFile(new URL("../drizzle/0006_brainy_falcon.sql", import.meta.url), "utf8");
  const analysisRecovery = await readFile(new URL("../drizzle/0007_special_ben_grimm.sql", import.meta.url), "utf8");
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  applyMigration(db, initial);
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("user-1", "Tester");
  db.prepare(`
    INSERT INTO orders (
      id, user_id, product_code, checkout_attempt_id, match_id,
      amount_kopecks, status, yookassa_payment_id, credited_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    "54e86508-e78b-4ff6-b3db-4116930b5027",
    "user-1",
    "single_analysis",
    "733a774e-6765-40da-b971-ad4b205d2429",
    "8963624400",
    29_900,
    "succeeded",
    "payment-123456",
    "2026-09-04 00:00:00",
  );

  applyMigration(db, foundation);
  applyMigration(db, guards);
  applyMigration(db, slotGuard);
  applyMigration(db, bucketGuard);
  applyMigration(db, unsettledCoachGuard);
  applyMigration(db, paymentStateGuards);
  applyMigration(db, analysisRecovery);

  const order = db.prepare("SELECT * FROM orders WHERE id = ?").get(
    "54e86508-e78b-4ff6-b3db-4116930b5027",
  );
  assert.equal(order.amount_kopecks, 29_900);
  assert.equal(order.product_version, "legacy-v0");
  assert.equal(order.payment_mode, "unknown");
  assert.equal(order.provider_idempotency_key, order.id);
  assert.equal(order.grant_analyses, 1);
  assert.equal(order.grant_coach_questions, 10);
  assert.equal(order.fulfillment_status, "granted");

  const opening = db.prepare(`
    SELECT resource, delta FROM entitlement_ledger
    WHERE user_id = ? ORDER BY resource
  `).all("user-1");
  assert.deepEqual(opening.map((row) => ({ ...row })), [
    { resource: "analysis", delta: 1 },
    { resource: "coach_question", delta: 5 },
  ]);
  assert.deepEqual(db.prepare("PRAGMA foreign_key_check").all(), []);
  db.close();
});

test("financial records survive a hard user deletion as a final safety net", async () => {
  const initial = await readFile(new URL("../drizzle/0000_abandoned_stone_men.sql", import.meta.url), "utf8");
  const foundation = await readFile(new URL("../drizzle/0001_billing_foundation.sql", import.meta.url), "utf8");
  const guards = await readFile(new URL("../drizzle/0002_ledger_resolution_guards.sql", import.meta.url), "utf8");
  const slotGuard = await readFile(new URL("../drizzle/0003_dota_player_slot_guard.sql", import.meta.url), "utf8");
  const bucketGuard = await readFile(new URL("../drizzle/0004_entitlement_bucket_uniqueness.sql", import.meta.url), "utf8");
  const unsettledCoachGuard = await readFile(new URL("../drizzle/0005_block_unsettled_coach_orders.sql", import.meta.url), "utf8");
  const paymentStateGuards = await readFile(new URL("../drizzle/0006_brainy_falcon.sql", import.meta.url), "utf8");
  const analysisRecovery = await readFile(new URL("../drizzle/0007_special_ben_grimm.sql", import.meta.url), "utf8");
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  applyMigration(db, initial);
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("user-2", "Tester");
  db.prepare(`
    INSERT INTO orders (id, user_id, product_code, checkout_attempt_id, amount_kopecks)
    VALUES (?, ?, ?, ?, ?)
  `).run(
    "e0788292-806b-4c48-a843-54e191e9e68f",
    "user-2",
    "coach_30_days",
    "d2de1d1f-acb6-45d1-9cd7-6bc3c5d4b48c",
    79_900,
  );
  applyMigration(db, foundation);
  applyMigration(db, guards);
  applyMigration(db, slotGuard);
  applyMigration(db, bucketGuard);
  applyMigration(db, unsettledCoachGuard);
  applyMigration(db, paymentStateGuards);
  applyMigration(db, analysisRecovery);
  db.prepare("DELETE FROM users WHERE id = ?").run("user-2");
  const retained = db.prepare("SELECT user_id, amount_kopecks FROM orders WHERE id = ?").get(
    "e0788292-806b-4c48-a843-54e191e9e68f",
  );
  assert.deepEqual({ ...retained }, { user_id: null, amount_kopecks: 79_900 });
  db.close();
});

test("empty migration chain is valid and creates cleanup and idempotency indexes", async () => {
  const files = await Promise.all([
    "../drizzle/0000_abandoned_stone_men.sql",
    "../drizzle/0001_billing_foundation.sql",
    "../drizzle/0002_ledger_resolution_guards.sql",
    "../drizzle/0003_dota_player_slot_guard.sql",
    "../drizzle/0004_entitlement_bucket_uniqueness.sql",
    "../drizzle/0005_block_unsettled_coach_orders.sql",
    "../drizzle/0006_brainy_falcon.sql",
    "../drizzle/0007_special_ben_grimm.sql",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")));
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  assert.ok(
    files[5].indexOf("CREATE UNIQUE INDEX `orders_one_unresolved_coach_per_user`")
      < files[5].indexOf("DROP INDEX `orders_one_open_coach_per_user`"),
    "the stricter index must be created before the old guard is dropped",
  );
  for (const migration of files) applyMigration(db, migration);
  assert.deepEqual(db.prepare("PRAGMA foreign_key_check").all(), []);
  const indexes = db.prepare(`
    SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name
  `).all().map((row) => row.name);
  assert.ok(indexes.includes("analysis_jobs_user_idempotency_unique"));
  assert.ok(indexes.includes("analysis_jobs_active_report_identity_unique"));
  assert.ok(!indexes.includes("analysis_jobs_report_identity_unique"));
  assert.ok(indexes.includes("rate_limit_buckets_cleanup_idx"));
  assert.ok(!indexes.includes("provider_events_delivery_unique"));
  assert.ok(indexes.includes("provider_events_transition_unique"));
  assert.ok(indexes.includes("orders_one_unresolved_coach_per_user"));
  const triggers = db.prepare(`
    SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name
  `).all().map((row) => row.name);
  assert.ok(triggers.includes("entitlement_ledger_immutable_update"));
  assert.ok(triggers.includes("provider_events_immutable_delete"));
  assert.ok(triggers.includes("analysis_reports_immutable_update"));
  assert.ok(triggers.includes("orders_snapshot_immutable_update"));
  assert.ok(triggers.includes("orders_lifecycle_monotonic_update"));
  const analysisJobColumns = db.prepare("PRAGMA table_info(analysis_jobs)").all()
    .map((row) => row.name);
  assert.ok(analysisJobColumns.includes("retry_not_before"));
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("slot-user", "Tester");
  const insertJob = db.prepare(`
    INSERT INTO analysis_jobs (
      id, user_id, match_id, player_slot, report_version, idempotency_key, request_hash
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
  `);
  assert.throws(
    () => insertJob.run("job-invalid", "slot-user", "8963624400", 5, "v1", "idem-invalid", "hash-invalid"),
    /invalid Dota player slot|CHECK constraint failed/,
  );
  insertJob.run("job-valid", "slot-user", "8963624400", 132, "v1", "idem-valid", "hash-valid");
  db.close();
});

test("unresolved succeeded coach payments block a second subscription order", async () => {
  const files = await Promise.all([
    "../drizzle/0000_abandoned_stone_men.sql",
    "../drizzle/0001_billing_foundation.sql",
    "../drizzle/0002_ledger_resolution_guards.sql",
    "../drizzle/0003_dota_player_slot_guard.sql",
    "../drizzle/0004_entitlement_bucket_uniqueness.sql",
    "../drizzle/0005_block_unsettled_coach_orders.sql",
    "../drizzle/0006_brainy_falcon.sql",
    "../drizzle/0007_special_ben_grimm.sql",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")));
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  for (const migration of files) applyMigration(db, migration);
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("coach-user", "Tester");
  const insertCoach = db.prepare(`
    INSERT INTO orders (
      id, user_id, product_code, checkout_attempt_id, amount_kopecks,
      status, fulfillment_status, credited_at
    ) VALUES (?, 'coach-user', 'coach_30_days', ?, 79900, ?, ?, ?)
  `);

  insertCoach.run("paid-unresolved", "attempt-paid-unresolved", "succeeded", "not_granted", null);
  assert.throws(
    () => insertCoach.run("second-open", "attempt-second-open", "created", "not_granted", null),
    /UNIQUE constraint failed/,
  );

  db.prepare(`
    UPDATE orders
    SET credited_at = CURRENT_TIMESTAMP, fulfillment_status = 'granted'
    WHERE id = 'paid-unresolved'
  `).run();
  insertCoach.run("second-open", "attempt-second-open", "created", "not_granted", null);
  db.prepare("UPDATE orders SET status = 'canceled' WHERE id = 'second-open'").run();

  insertCoach.run(
    "manual-review",
    "attempt-manual-review",
    "succeeded",
    "manual_review",
    "2026-09-04 00:00:00",
  );
  assert.throws(
    () => insertCoach.run("third-open", "attempt-third-open", "created", "not_granted", null),
    /UNIQUE constraint failed/,
  );

  db.prepare("UPDATE orders SET fulfillment_status = 'granted' WHERE id = 'manual-review'").run();
  insertCoach.run("third-open", "attempt-third-open", "created", "not_granted", null);
  assert.equal(
    db.prepare(`
      SELECT COUNT(*) AS total
      FROM orders
      WHERE user_id = 'coach-user'
        AND product_code = 'coach_30_days'
        AND status IN ('created', 'pending', 'waiting_for_capture')
    `).get().total,
    1,
  );
  db.close();
});

test("ledger accepts one exact resolution and rejects mutation or minted release", async () => {
  const files = await Promise.all([
    "../drizzle/0000_abandoned_stone_men.sql",
    "../drizzle/0001_billing_foundation.sql",
    "../drizzle/0002_ledger_resolution_guards.sql",
    "../drizzle/0003_dota_player_slot_guard.sql",
    "../drizzle/0004_entitlement_bucket_uniqueness.sql",
    "../drizzle/0005_block_unsettled_coach_orders.sql",
    "../drizzle/0006_brainy_falcon.sql",
    "../drizzle/0007_special_ben_grimm.sql",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")));
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  for (const migration of files) applyMigration(db, migration);
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("user-3", "Tester");
  const insert = db.prepare(`
    INSERT INTO entitlement_ledger (
      id, user_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id, resolution_of
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  insert.run("grant-1", "user-3", "grant", "analysis", "bucket-1", 1, "grant-key", "free_trial", "user-3", null);
  assert.throws(
    () => insert.run("grant-2", "user-3", "grant", "analysis", "bucket-1", 1, "grant-key-2", "manual_adjustment", "user-3", null),
    /UNIQUE constraint failed/,
  );
  insert.run("reserve-1", "user-3", "reserve", "analysis", "bucket-1", -1, "reserve-key", "analysis_job", "job-1", null);

  assert.throws(
    () => insert.run("release-bad", "user-3", "release", "analysis", "bucket-1", 999, "release-bad-key", "analysis_job", "job-1", "reserve-1"),
    /invalid entitlement reservation resolution/,
  );
  insert.run("release-1", "user-3", "release", "analysis", "bucket-1", 1, "release-key", "analysis_job", "job-1", "reserve-1");
  assert.throws(
    () => insert.run("consume-1", "user-3", "consume", "analysis", "bucket-1", 0, "consume-key", "analysis_job", "job-1", "reserve-1"),
    /UNIQUE constraint failed/,
  );
  assert.throws(
    () => db.prepare("UPDATE entitlement_ledger SET delta = 2 WHERE id = 'grant-1'").run(),
    /entitlement ledger is immutable/,
  );
  db.close();
});

test("settlement entitlement conflicts fail closed instead of crediting projections", async () => {
  const files = await Promise.all([
    "../drizzle/0000_abandoned_stone_men.sql",
    "../drizzle/0001_billing_foundation.sql",
    "../drizzle/0002_ledger_resolution_guards.sql",
    "../drizzle/0003_dota_player_slot_guard.sql",
    "../drizzle/0004_entitlement_bucket_uniqueness.sql",
    "../drizzle/0005_block_unsettled_coach_orders.sql",
    "../drizzle/0006_brainy_falcon.sql",
    "../drizzle/0007_special_ben_grimm.sql",
  ].map((path) => readFile(new URL(path, import.meta.url), "utf8")));
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys=ON");
  for (const migration of files) applyMigration(db, migration);
  db.prepare("INSERT INTO users (id, display_name) VALUES (?, ?)").run("user-4", "Tester");
  db.prepare(`
    INSERT INTO entitlement_ledger (
      id, user_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id
    ) VALUES (?, ?, 'grant', 'analysis', ?, ?, ?, 'manual_adjustment', ?)
  `).run(
    "poisoned-grant",
    "user-4",
    "billing-order:order-4",
    99,
    "billing-order:order-4:analysis-grant",
    "order-4",
  );
  assert.throws(() => db.prepare(`
    INSERT INTO entitlement_ledger (
      id, user_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id
    ) VALUES (?, ?, 'grant', 'analysis', ?, ?, ?, 'billing_order', ?)
  `).run(
    "expected-grant",
    "user-4",
    "billing-order:order-4",
    1,
    "billing-order:order-4:analysis-grant",
    "order-4",
  ), /UNIQUE constraint failed/);
  const webhookSource = await readFile(
    new URL("../app/api/payments/webhook/route.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(webhookSource, /INSERT OR IGNORE INTO entitlement_ledger/);
  db.close();
});

test("ledger helpers create immutable bucketed grants and stable request hashes", async () => {
  const { entitlementGrantValues, freeTrialLedgerEntries } = await vite.ssrLoadModule(
    "/lib/billing/ledger.ts",
  );
  const { billingRequestHash, serializeBillingRequest } = await vite.ssrLoadModule(
    "/lib/billing/order-idempotency.ts",
  );
  const grants = freeTrialLedgerEntries("4b3825b0-57fd-4fbd-93c7-b9d9dafdf5ce");
  assert.equal(grants.length, 2);
  assert.equal(grants[0].bucketKey, grants[1].bucketKey);
  assert.equal(grants[0].delta, 1);
  assert.equal(grants[1].delta, 5);
  assert.throws(() => entitlementGrantValues({
    userId: "user-1",
    resource: "analysis",
    bucketKey: "bucket-1",
    units: 0,
    idempotencyKey: "grant-1",
    referenceType: "manual_adjustment",
    referenceId: "ref-1",
  }), /positive safe integer/);

  const identity = {
    orderId: "54e86508-e78b-4ff6-b3db-4116930b5027",
    userId: "user-1",
    checkoutAttemptId: "attempt-1",
    productCode: "single_analysis",
    productVersion: "v1",
    matchId: "8963624400",
    amountKopecks: 29_900,
    currency: "RUB",
    grantAnalyses: 1,
    grantCoachQuestions: 10,
    durationDays: null,
    environment: "staging",
    paymentMode: "test",
    provider: "yookassa",
    providerShopId: "123456",
    providerIdempotencyKey: "54e86508-e78b-4ff6-b3db-4116930b5027",
  };
  assert.equal(await billingRequestHash(identity), await billingRequestHash(identity));
  assert.notEqual(
    await billingRequestHash(identity),
    await billingRequestHash({ ...identity, matchId: "8963624401" }),
  );
  assert.notEqual(
    await billingRequestHash(identity),
    await billingRequestHash({ ...identity, grantAnalyses: 10_000 }),
  );
  assert.equal(JSON.parse(serializeBillingRequest(identity)).amountKopecks, 29_900);
});

test("bounded JSON rejects wrong content type and oversized checkout bodies", async () => {
  const { BoundedJsonError, readBoundedJson } = await vite.ssrLoadModule(
    "/lib/security/bounded-json.ts",
  );
  assert.deepEqual(
    await readBoundedJson(new Request("https://example.test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productCode: "single_analysis" }),
    }), 1_024),
    { productCode: "single_analysis" },
  );
  await assert.rejects(
    readBoundedJson(new Request("https://example.test", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: "{}",
    }), 1_024),
    (error) => error instanceof BoundedJsonError && error.code === "content_type",
  );
  await assert.rejects(
    readBoundedJson(new Request("https://example.test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: "x".repeat(2_000) }),
    }), 1_024),
    (error) => error instanceof BoundedJsonError && error.code === "too_large",
  );
});

test("account balance reads the active immutable ledger, not legacy counters", async () => {
  const source = await readFile(
    new URL("../lib/auth/current-account.ts", import.meta.url),
    "utf8",
  );
  assert.match(source, /SELECT SUM\(delta\)[\s\S]+resource = 'analysis'/);
  assert.match(source, /expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP/);
  assert.doesNotMatch(source, /\$\{users\.analysisCredits\}\s*\+\s*\$\{users\.subscriptionAnalysisCredits\}/);
});
