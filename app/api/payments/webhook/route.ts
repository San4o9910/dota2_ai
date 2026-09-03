import { eq, sql } from "drizzle-orm";

import { getDb } from "@/db";
import { orders } from "@/db/schema";
import {
  BILLING_CATALOG,
  isPaidProductCode,
  yookassaAmount,
} from "@/lib/billing/catalog";
import {
  getYooKassaCredentials,
  paymentsEnabled,
} from "@/lib/payments/runtime";
import { isJsonObject } from "@/lib/security/json";
import {
  getYooKassaPayment,
  isConfirmedCheckoutPayment,
} from "@/lib/payments/yookassa";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PAYMENT_ID = /^[0-9a-z-]{8,64}$/i;

type Notification = {
  event?: unknown;
  object?: { id?: unknown };
};

export async function POST(request: Request) {
  if (!paymentsEnabled()) {
    return Response.json({ error: "Payments are disabled" }, { status: 503 });
  }

  let input: unknown;
  try {
    input = await request.json();
  } catch {
    return Response.json({ error: "Invalid notification" }, { status: 400 });
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

  const event = String(notification.event);
  const paymentId = notification.object.id;
  try {
    const db = getDb();
    const [order] = await db
      .select()
      .from(orders)
      .where(eq(orders.yookassaPaymentId, paymentId))
      .limit(1);
    if (!order) {
      // A webhook can beat the short local update immediately after checkout.
      // Returning 503 asks YooKassa to retry without spending an API lookup on
      // arbitrary public input.
      return Response.json({ error: "Order is not ready" }, { status: 503 });
    }
    if (
      (order.status === "succeeded" && order.creditedAt)
      || (order.status === "canceled" && event === "payment.canceled")
    ) {
      return Response.json({ accepted: true });
    }

    // The incoming payload is never trusted as payment proof. The authoritative
    // payment is fetched from YooKassa with server-side credentials.
    const payment = await getYooKassaPayment(
      getYooKassaCredentials(),
      paymentId,
    );
    const orderId = payment.metadata?.order_id;
    if (!orderId || !UUID.test(orderId) || orderId !== order.id) {
      return Response.json({ error: "Payment is not linked to an order" }, { status: 400 });
    }
    if (order.yookassaPaymentId !== payment.id) {
      return Response.json({ error: "Order was not found" }, { status: 404 });
    }

    if (payment.status === "canceled") {
      await db
        .update(orders)
        .set({ status: "canceled", updatedAt: sql`CURRENT_TIMESTAMP` })
        .where(eq(orders.id, order.id));
      return Response.json({ accepted: true });
    }

    if (!isPaidProductCode(order.productCode)) {
      return Response.json({ error: "Unknown order product" }, { status: 409 });
    }
    const product = BILLING_CATALOG[order.productCode];
    const confirmed = isConfirmedCheckoutPayment(payment, {
      orderId: order.id,
      productCode: product.code,
      matchId: order.matchId ?? undefined,
      amountRub: yookassaAmount(order.amountKopecks),
    });
    if (!confirmed) {
      return Response.json({ error: "Payment details do not match the order" }, { status: 409 });
    }

    const creditUpdate = product.durationDays
      ? db.run(sql`
          UPDATE users
          SET subscription_analysis_credits = ${product.analyses},
              subscription_coach_questions_remaining = ${product.coachQuestions},
              plan_code = ${product.code},
              plan_expires_at = datetime(CURRENT_TIMESTAMP, ${`+${product.durationDays} days`}),
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ${order.userId}
            AND EXISTS (
              SELECT 1 FROM orders
              WHERE id = ${order.id} AND credited_at IS NULL
            )
        `)
      : db.run(sql`
          UPDATE users
          SET analysis_credits = analysis_credits + ${product.analyses},
              coach_questions_remaining = coach_questions_remaining + ${product.coachQuestions},
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ${order.userId}
            AND EXISTS (
              SELECT 1 FROM orders
              WHERE id = ${order.id} AND credited_at IS NULL
            )
        `);

    // D1 batches are atomic and sequential. The credited_at guard makes repeat
    // notifications idempotent: a paid order can grant its credits only once.
    await db.batch([
      db
        .update(orders)
        .set({ status: "succeeded", updatedAt: sql`CURRENT_TIMESTAMP` })
        .where(eq(orders.id, order.id)),
      creditUpdate,
      db.run(sql`
        UPDATE orders
        SET credited_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ${order.id} AND credited_at IS NULL
      `),
    ]);

    return Response.json({ accepted: true });
  } catch (error) {
    console.error("YooKassa webhook verification failed", {
      paymentId,
      error: error instanceof Error ? error.name : "UnknownError",
    });
    // A non-2xx response asks YooKassa to retry a transient delivery failure.
    return Response.json({ error: "Payment verification failed" }, { status: 503 });
  }
}
