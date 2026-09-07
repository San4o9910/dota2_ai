import { and, eq, sql } from "drizzle-orm";

import { getDb } from "@/db";
import { orders, providerEvents } from "@/db/schema";
import { yookassaAmount } from "@/lib/billing/catalog";
import { entitlementGrantValues } from "@/lib/billing/ledger";
import { billingRequestHash } from "@/lib/billing/order-idempotency";
import {
  getPaymentSettlementIdentity,
  getYooKassaCredentials,
  paymentSettlementEnabled,
} from "@/lib/payments/runtime";
import { isJsonContentType } from "@/lib/security/content-type";
import { isJsonObject } from "@/lib/security/json";
import {
  getYooKassaPayment,
  isConfirmedCheckoutPayment,
  checkoutPaymentMatchesOrder,
  paymentMatchesMode,
} from "@/lib/payments/yookassa";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PAYMENT_ID = /^[0-9a-z-]{8,64}$/i;
const MAX_NOTIFICATION_BYTES = 16 * 1024;

type Notification = {
  event?: unknown;
  object?: { id?: unknown };
};

async function readNotification(request: Request) {
  if (!isJsonContentType(request.headers.get("content-type"))) {
    throw new Error("notification_content_type");
  }
  const declaredLength = request.headers.get("content-length");
  if (declaredLength && Number(declaredLength) > MAX_NOTIFICATION_BYTES) {
    throw new Error("notification_too_large");
  }
  const reader = request.body?.getReader();
  if (!reader) throw new Error("notification_empty");
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    if (bytes > MAX_NOTIFICATION_BYTES) {
      await reader.cancel();
      throw new Error("notification_too_large");
    }
    chunks.push(value);
  }
  const raw = new Uint8Array(bytes);
  let offset = 0;
  for (const chunk of chunks) {
    raw.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let input: unknown;
  try {
    input = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    throw new Error("notification_json");
  }
  const digest = await crypto.subtle.digest("SHA-256", raw);
  const payloadHash = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return { input, payloadHash };
}

function sqliteTimestampAfterDays(days: number) {
  return new Date(Date.now() + days * 86_400_000)
    .toISOString()
    .replace("T", " ")
    .slice(0, 19);
}

export async function POST(request: Request) {
  // Settlement deliberately does not depend on the checkout kill switch. This
  // lets an operator stop new sales while completing already-created orders.
  if (!paymentSettlementEnabled()) {
    return Response.json({ error: "Payment settlement is disabled" }, { status: 503 });
  }

  let input: unknown;
  let payloadHash: string;
  try {
    ({ input, payloadHash } = await readNotification(request));
  } catch (error) {
    const tooLarge = error instanceof Error && error.message === "notification_too_large";
    return Response.json(
      { error: "Invalid notification" },
      { status: tooLarge ? 413 : 400 },
    );
  }
  if (!isJsonObject(input)) {
    return Response.json({ error: "Invalid notification" }, { status: 400 });
  }
  const object = isJsonObject(input.object) ? input.object : null;
  const notification: Notification = { event: input.event, object: object ?? undefined };

  if (
    !["payment.succeeded", "payment.canceled"].includes(String(notification.event))
    || typeof notification.object?.id !== "string"
    || !PAYMENT_ID.test(notification.object.id)
  ) {
    return Response.json({ accepted: true });
  }

  const paymentId = notification.object.id;
  try {
    const runtimeIdentity = getPaymentSettlementIdentity();
    const db = getDb();
    const [order] = await db
      .select()
      .from(orders)
      .where(eq(orders.yookassaPaymentId, paymentId))
      .limit(1);
    if (!order) {
      // A webhook can beat the local update immediately after checkout.
      return Response.json({ error: "Order is not ready" }, { status: 503 });
    }
    if (
      !order.userId
      || order.environment !== runtimeIdentity.environment
      || order.paymentMode !== runtimeIdentity.paymentMode
      || order.providerShopId !== runtimeIdentity.providerShopId
      || order.provider !== "yookassa"
      || order.providerIdempotencyKey !== order.id
      || order.currency !== "RUB"
    ) {
      return Response.json({ error: "Order environment does not match" }, { status: 409 });
    }
    const expectedRequestHash = await billingRequestHash({
      orderId: order.id,
      userId: order.userId,
      checkoutAttemptId: order.checkoutAttemptId,
      productCode: order.productCode,
      productVersion: order.productVersion,
      matchId: order.matchId,
      amountKopecks: order.amountKopecks,
      currency: "RUB",
      grantAnalyses: order.grantAnalyses,
      grantCoachQuestions: order.grantCoachQuestions,
      durationDays: order.durationDays,
      environment: order.environment,
      paymentMode: runtimeIdentity.paymentMode,
      provider: "yookassa",
      providerShopId: runtimeIdentity.providerShopId,
      providerIdempotencyKey: order.id,
    });
    if (order.requestHash !== expectedRequestHash) {
      await db.run(sql`
        UPDATE orders
        SET fulfillment_status = CASE
              WHEN credited_at IS NULL AND fulfillment_status <> 'granted'
                THEN 'manual_review'
              ELSE fulfillment_status
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ${order.id}
      `);
      return Response.json({ error: "Order integrity check failed" }, { status: 409 });
    }
    if (
      (order.paymentStatus === "succeeded"
        && order.creditedAt
        && order.fulfillmentStatus === "granted")
      || order.paymentStatus === "canceled"
    ) {
      return Response.json({ accepted: true });
    }

    // The incoming payload is never payment proof. Fetch the authoritative
    // payment using the settlement gate's mode-specific credentials.
    const payment = await getYooKassaPayment(
      getYooKassaCredentials("settlement"),
      paymentId,
    );
    if (
      !paymentMatchesMode(payment, runtimeIdentity.paymentMode)
      || (order.providerTest !== null && order.providerTest !== payment.test)
    ) {
      return Response.json({ error: "Payment mode does not match the order" }, { status: 409 });
    }
    const orderId = payment.metadata?.order_id;
    if (!orderId || !UUID.test(orderId) || orderId !== order.id) {
      return Response.json({ error: "Payment is not linked to an order" }, { status: 400 });
    }
    if (order.yookassaPaymentId !== payment.id) {
      return Response.json({ error: "Order was not found" }, { status: 404 });
    }

    const verifiedEventValues = (
      eventType: "payment.succeeded" | "payment.canceled",
    ) => ({
      id: crypto.randomUUID(),
      orderId: order.id,
      provider: "yookassa",
      eventType,
      providerPaymentId: payment.id,
      payloadHash,
      paymentMode: runtimeIdentity.paymentMode,
      providerTest: payment.test,
    });

    if (!checkoutPaymentMatchesOrder(payment, {
      orderId: order.id, productCode: order.productCode,
      matchId: order.matchId ?? undefined, amountRub: yookassaAmount(order.amountKopecks),
    }, runtimeIdentity.paymentMode)) {
      return Response.json({ error: "Payment details do not match the order" }, { status: 409 });
    }
    if (payment.status === "pending" || payment.status === "waiting_for_capture") {
      return Response.json({ accepted: true, pending: true }, { status: 202 });
    }

    if (payment.status === "canceled") {
      await db.batch([
        db
          .insert(providerEvents)
          .values(verifiedEventValues("payment.canceled"))
          .onConflictDoNothing(),
        db
          .update(orders)
          .set({
            paymentStatus: "canceled",
            providerTest: payment.test,
            updatedAt: sql`CURRENT_TIMESTAMP`,
          })
          .where(and(eq(orders.id, order.id), sql`${orders.paymentStatus} <> 'succeeded' AND ${orders.creditedAt} IS NULL`)),
      ]);
      return Response.json({ accepted: true });
    }

    const confirmed = isConfirmedCheckoutPayment(payment, {
      orderId: order.id,
      productCode: order.productCode,
      matchId: order.matchId ?? undefined,
      amountRub: yookassaAmount(order.amountKopecks),
    }, runtimeIdentity.paymentMode);
    if (!confirmed) {
      return Response.json({ error: "Payment details do not match the order" }, { status: 409 });
    }
    if (
      !Number.isSafeInteger(order.grantAnalyses)
      || order.grantAnalyses < 1
      || !Number.isSafeInteger(order.grantCoachQuestions)
      || order.grantCoachQuestions < 1
      || (order.durationDays !== null
        && (!Number.isSafeInteger(order.durationDays)
          || order.durationDays < 1
          || order.durationDays > 3_650))
    ) {
      return Response.json({ error: "Order grant snapshot is invalid" }, { status: 409 });
    }

    const expiresAt = order.durationDays
      ? sqliteTimestampAfterDays(order.durationDays)
      : null;
    const bucketKey = `billing-order:${order.id}`;
    const analysisGrant = entitlementGrantValues({
      userId: order.userId,
      orderId: order.id,
      resource: "analysis",
      bucketKey,
      units: order.grantAnalyses,
      idempotencyKey: `${bucketKey}:analysis-grant`,
      referenceType: "billing_order",
      referenceId: order.id,
      productCode: order.productCode,
      productVersion: order.productVersion,
      expiresAt,
    });
    const questionGrant = entitlementGrantValues({
      userId: order.userId,
      orderId: order.id,
      resource: "coach_question",
      bucketKey,
      units: order.grantCoachQuestions,
      idempotencyKey: `${bucketKey}:question-grant`,
      referenceType: "billing_order",
      referenceId: order.id,
      productCode: order.productCode,
      productVersion: order.productVersion,
      expiresAt,
    });

    const planUpdate = db.run(sql`
      UPDATE users
      SET plan_code = CASE
            WHEN ${order.durationDays} IS NOT NULL THEN ${order.productCode}
            ELSE plan_code
          END,
          plan_expires_at = CASE
            WHEN ${order.durationDays} IS NOT NULL THEN ${expiresAt}
            ELSE plan_expires_at
          END,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ${order.userId}
        AND status = 'active'
        AND EXISTS (
          SELECT 1 FROM orders
          WHERE id = ${order.id} AND credited_at IS NULL
        )
    `);

    // D1 batches are atomic and sequential. Unique ledger keys plus the
    // credited_at guard make repeated delivery idempotent.
    await db.batch([
      db
        .insert(providerEvents)
        .values(verifiedEventValues("payment.succeeded"))
        .onConflictDoNothing(),
      db
        .update(orders)
        .set({
          paymentStatus: "succeeded",
          providerTest: payment.test,
          updatedAt: sql`CURRENT_TIMESTAMP`,
        })
        .where(eq(orders.id, order.id)),
      db.run(sql`
        INSERT INTO entitlement_ledger (
          id, user_id, order_id, entry_type, resource, bucket_key, delta,
          idempotency_key, reference_type, reference_id, resolution_of,
          product_code, product_version, expires_at
        )
        SELECT
          ${analysisGrant.id}, ${analysisGrant.userId}, ${analysisGrant.orderId},
          ${analysisGrant.entryType}, ${analysisGrant.resource}, ${analysisGrant.bucketKey},
          ${analysisGrant.delta}, ${analysisGrant.idempotencyKey},
          ${analysisGrant.referenceType}, ${analysisGrant.referenceId}, NULL,
          ${analysisGrant.productCode}, ${analysisGrant.productVersion}, ${analysisGrant.expiresAt}
        WHERE EXISTS (
          SELECT 1 FROM users WHERE id = ${order.userId} AND status = 'active'
        ) AND EXISTS (
          SELECT 1 FROM orders WHERE id = ${order.id} AND credited_at IS NULL
        )
      `),
      db.run(sql`
        INSERT INTO entitlement_ledger (
          id, user_id, order_id, entry_type, resource, bucket_key, delta,
          idempotency_key, reference_type, reference_id, resolution_of,
          product_code, product_version, expires_at
        )
        SELECT
          ${questionGrant.id}, ${questionGrant.userId}, ${questionGrant.orderId},
          ${questionGrant.entryType}, ${questionGrant.resource}, ${questionGrant.bucketKey},
          ${questionGrant.delta}, ${questionGrant.idempotencyKey},
          ${questionGrant.referenceType}, ${questionGrant.referenceId}, NULL,
          ${questionGrant.productCode}, ${questionGrant.productVersion}, ${questionGrant.expiresAt}
        WHERE EXISTS (
          SELECT 1 FROM users WHERE id = ${order.userId} AND status = 'active'
        ) AND EXISTS (
          SELECT 1 FROM orders WHERE id = ${order.id} AND credited_at IS NULL
        )
      `),
      planUpdate,
      db.run(sql`
        UPDATE orders
        SET credited_at = CASE
              WHEN EXISTS (
                SELECT 1 FROM users WHERE id = ${order.userId} AND status = 'active'
              ) THEN CURRENT_TIMESTAMP
              ELSE credited_at
            END,
            fulfillment_status = CASE
              WHEN EXISTS (
                SELECT 1 FROM users WHERE id = ${order.userId} AND status = 'active'
              ) THEN 'granted'
              ELSE 'manual_review'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ${order.id} AND credited_at IS NULL
      `),
    ]);

    return Response.json({ accepted: true });
  } catch (error) {
    console.error("YooKassa webhook verification failed", {
      paymentId,
      error: error instanceof Error ? error.name : "UnknownError",
    });
    // Provider auth/configuration failures are dependency failures, not a user
    // 401/402. A 503 asks YooKassa to retry transient delivery failures.
    return Response.json({ error: "Payment verification failed" }, { status: 503 });
  }
}
