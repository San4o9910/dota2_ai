import { eq, sql } from "drizzle-orm";

import type { getDb } from "@/db";
import { entitlementLedger } from "@/db/schema";

export type EntitlementResource = "analysis" | "coach_question";
export type LedgerResolution = "consume" | "release";
type Database = ReturnType<typeof getDb>;

type GrantInput = {
  id?: string;
  userId: string;
  orderId?: string | null;
  resource: EntitlementResource;
  bucketKey: string;
  units: number;
  idempotencyKey: string;
  referenceType: "free_trial" | "billing_order" | "manual_adjustment";
  referenceId: string;
  productCode?: string | null;
  productVersion?: string | null;
  expiresAt?: string | null;
};

type ReserveInput = {
  id?: string;
  userId: string;
  resource: EntitlementResource;
  bucketKey: string;
  units?: number;
  idempotencyKey: string;
  referenceType: "analysis_job" | "coach_message";
  referenceId: string;
};

const SAFE_KEY = /^[a-zA-Z0-9:._-]{1,240}$/;

function positiveUnits(units: number) {
  if (!Number.isSafeInteger(units) || units < 1 || units > 10_000) {
    throw new Error("Entitlement units must be a positive safe integer");
  }
  return units;
}

function safeKey(value: string, label: string) {
  if (!SAFE_KEY.test(value)) throw new Error(`${label} is invalid`);
  return value;
}

export function entitlementGrantValues(input: GrantInput) {
  return {
    id: input.id ?? crypto.randomUUID(),
    userId: safeKey(input.userId, "userId"),
    orderId: input.orderId ?? null,
    entryType: "grant" as const,
    resource: input.resource,
    bucketKey: safeKey(input.bucketKey, "bucketKey"),
    delta: positiveUnits(input.units),
    idempotencyKey: safeKey(input.idempotencyKey, "idempotencyKey"),
    referenceType: input.referenceType,
    referenceId: safeKey(input.referenceId, "referenceId"),
    resolutionOf: null,
    productCode: input.productCode ?? null,
    productVersion: input.productVersion ?? null,
    expiresAt: input.expiresAt ?? null,
  };
}

// A bucket has exactly one grant per resource (enforced by a partial unique
// index). A manual adjustment therefore always receives a fresh bucket key.

export function freeTrialLedgerEntries(userId: string) {
  const bucketKey = `free-trial:${userId}:v1`;
  return [
    entitlementGrantValues({
      userId,
      resource: "analysis",
      bucketKey,
      units: 1,
      idempotencyKey: `${bucketKey}:analysis`,
      referenceType: "free_trial",
      referenceId: userId,
      productCode: "free_trial",
      productVersion: "v1",
    }),
    entitlementGrantValues({
      userId,
      resource: "coach_question",
      bucketKey,
      units: 5,
      idempotencyKey: `${bucketKey}:coach-question`,
      referenceType: "free_trial",
      referenceId: userId,
      productCode: "free_trial",
      productVersion: "v1",
    }),
  ];
}

/**
 * Reserves units with one INSERT ... SELECT statement. D1 serializes this
 * balance check and insert atomically. Callers choose a concrete grant bucket,
 * so expiration never leaks a consumed unit into a later subscription.
 */
export async function reserveEntitlement(db: Database, input: ReserveInput) {
  const id = input.id ?? crypto.randomUUID();
  const units = positiveUnits(input.units ?? 1);
  const userId = safeKey(input.userId, "userId");
  const bucketKey = safeKey(input.bucketKey, "bucketKey");
  const idempotencyKey = safeKey(input.idempotencyKey, "idempotencyKey");
  const referenceId = safeKey(input.referenceId, "referenceId");

  await db.run(sql`
    INSERT INTO entitlement_ledger (
      id, user_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id, expires_at
    )
    SELECT
      ${id}, ${userId}, 'reserve', ${input.resource}, ${bucketKey}, ${-units},
      ${idempotencyKey}, ${input.referenceType}, ${referenceId}, (
        SELECT expires_at
        FROM entitlement_ledger
        WHERE user_id = ${userId}
          AND resource = ${input.resource}
          AND bucket_key = ${bucketKey}
          AND entry_type = 'grant'
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        ORDER BY expires_at IS NULL, expires_at, created_at
        LIMIT 1
      )
    WHERE NOT EXISTS (
      SELECT 1 FROM entitlement_ledger
      WHERE idempotency_key = ${idempotencyKey}
    )
      AND (
        SELECT COALESCE(SUM(delta), 0)
        FROM entitlement_ledger
        WHERE user_id = ${userId}
          AND resource = ${input.resource}
          AND bucket_key = ${bucketKey}
          AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
      ) >= ${units}
    ON CONFLICT(idempotency_key) DO NOTHING
  `);

  const [entry] = await db
    .select()
    .from(entitlementLedger)
    .where(eq(entitlementLedger.idempotencyKey, idempotencyKey))
    .limit(1);
  if (!entry) return { ok: false as const, reason: "insufficient_balance" as const };
  if (
    entry.entryType !== "reserve"
    || entry.userId !== userId
    || entry.resource !== input.resource
    || entry.bucketKey !== bucketKey
    || entry.referenceType !== input.referenceType
    || entry.referenceId !== referenceId
    || entry.delta !== -units
  ) {
    return { ok: false as const, reason: "idempotency_conflict" as const };
  }
  return { ok: true as const, reservationId: entry.id, replayed: entry.id !== id };
}

/** Consume or release a reservation exactly once. Concurrent opposite
 * resolutions race on the unique resolution_of index; only one is retained. */
export async function resolveEntitlementReservation(
  db: Database,
  reservationId: string,
  resolution: LedgerResolution,
) {
  safeKey(reservationId, "reservationId");
  const id = crypto.randomUUID();
  const idempotencyKey = `reservation:${reservationId}:${resolution}`;
  await db.run(sql`
    INSERT INTO entitlement_ledger (
      id, user_id, order_id, entry_type, resource, bucket_key, delta,
      idempotency_key, reference_type, reference_id, resolution_of,
      product_code, product_version, expires_at
    )
    SELECT
      ${id}, user_id, order_id, ${resolution}, resource, bucket_key,
      CASE WHEN ${resolution} = 'release' THEN -delta ELSE 0 END,
      ${idempotencyKey}, reference_type, reference_id, id,
      product_code, product_version, expires_at
    FROM entitlement_ledger
    WHERE id = ${reservationId} AND entry_type = 'reserve'
      AND NOT EXISTS (
        SELECT 1 FROM entitlement_ledger WHERE resolution_of = ${reservationId}
      )
    ON CONFLICT(resolution_of) WHERE resolution_of IS NOT NULL DO NOTHING
  `);

  const [entry] = await db
    .select()
    .from(entitlementLedger)
    .where(eq(entitlementLedger.resolutionOf, reservationId))
    .limit(1);
  if (!entry) return { ok: false as const, reason: "reservation_not_found" as const };
  if (entry.entryType !== resolution) {
    return { ok: false as const, reason: "already_resolved" as const };
  }
  return { ok: true as const, replayed: entry.id !== id };
}
