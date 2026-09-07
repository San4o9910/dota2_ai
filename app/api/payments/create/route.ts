import { and, count, eq, gte, inArray, isNull, ne, or, sql } from "drizzle-orm";

import { getChatGPTUser } from "@/app/chatgpt-auth";
import { getDb } from "@/db";
import { orders } from "@/db/schema";
import {
  BILLING_CATALOG,
  isPaidProductCode,
  yookassaAmount,
} from "@/lib/billing/catalog";
import { billingRequestHash } from "@/lib/billing/order-idempotency";
import { getOrCreateCurrentAccount } from "@/lib/auth/current-account";
import {
  getPaymentRuntimeIdentity,
  getYooKassaCredentials,
  paymentsEnabled,
} from "@/lib/payments/runtime";
import {
  checkoutPaymentMatchesOrder,
  createCheckoutPayment,
  getYooKassaPayment,
  isConfirmedCheckoutPayment,
  YooKassaError,
} from "@/lib/payments/yookassa";
import { paymentRouteFailure } from "@/lib/payments/route-error";
import { isSameOriginRequest, sameOriginError } from "@/lib/security/same-origin";
import { isJsonObject } from "@/lib/security/json";
import { BoundedJsonError, readBoundedJson } from "@/lib/security/bounded-json";

export const dynamic = "force-dynamic";

const MATCH_ID = /^\d{8,12}$/;
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_CHECKOUT_REQUEST_BYTES = 4 * 1024;

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) return sameOriginError();

  const user = await getChatGPTUser();
  if (!user) {
    return Response.json(
      { error: "Войдите или создайте аккаунт перед оплатой." },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  let input: unknown;
  try {
    input = await readBoundedJson(request, MAX_CHECKOUT_REQUEST_BYTES);
  } catch (error) {
    const tooLarge = error instanceof BoundedJsonError && error.code === "too_large";
    return Response.json(
      { error: tooLarge ? "Данные заказа слишком большие." : "Не удалось прочитать данные заказа." },
      { status: tooLarge ? 413 : 400 },
    );
  }
  if (!isJsonObject(input)) {
    return Response.json({ error: "Данные заказа должны быть объектом." }, { status: 400 });
  }
  const payload = input;

  if (!isPaidProductCode(payload.productCode)) {
    return Response.json({ error: "Неизвестный тариф." }, { status: 400 });
  }

  const checkoutAttemptId = typeof payload.checkoutAttemptId === "string"
    ? payload.checkoutAttemptId
    : "";
  if (!UUID_V4.test(checkoutAttemptId)) {
    return Response.json(
      { error: "Обновите страницу и повторите выбор тарифа." },
      { status: 400 },
    );
  }

  const matchId = typeof payload.matchId === "string" ? payload.matchId.trim() : "";
  if (matchId && !MATCH_ID.test(matchId)) {
    return Response.json({ error: "Match ID должен содержать от 8 до 12 цифр." }, { status: 400 });
  }
  if (payload.productCode === "single_analysis" && !matchId) {
    return Response.json({ error: "Для разового разбора укажите Match ID." }, { status: 400 });
  }

  if (!paymentsEnabled()) {
    return Response.json(
      {
        code: "PAYMENTS_NOT_ENABLED",
        error: "Тариф выбран. Реальные платежи включатся после оформления продавца и добавления тестового магазина ЮKassa.",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const product = BILLING_CATALOG[payload.productCode];

  try {
    const account = await getOrCreateCurrentAccount(user);
    if (account.status !== "active") {
      return Response.json(
        { error: "Оплата недоступна для этого аккаунта." },
        { status: 403, headers: { "Cache-Control": "no-store" } },
      );
    }
    const runtimeIdentity = getPaymentRuntimeIdentity();
    const expectedOrderIntegrity = (orderId: string) => ({
      orderId,
      userId: account.id,
      checkoutAttemptId,
      productCode: product.code,
      productVersion: product.version,
      matchId: matchId || null,
      amountKopecks: product.priceKopecks,
      currency: "RUB" as const,
      grantAnalyses: product.analyses,
      grantCoachQuestions: product.coachQuestions,
      durationDays: product.durationDays,
      environment: runtimeIdentity.environment,
      paymentMode: runtimeIdentity.paymentMode,
      provider: "yookassa" as const,
      providerShopId: runtimeIdentity.providerShopId,
      providerIdempotencyKey: orderId,
    });
    const db = getDb();
    if (product.code === "coach_30_days" && account.planCode === "coach_30_days") {
      return Response.json(
        { error: "Тариф AI-тренер уже активен. Продление станет доступно после окончания текущих 30 дней." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }
    let [order] = await db
      .select()
      .from(orders)
      .where(eq(orders.checkoutAttemptId, checkoutAttemptId))
      .limit(1);

    if (!order) {
      if (product.code === "coach_30_days") {
        const [openCoachOrder] = await db
          .select()
          .from(orders)
          .where(
            and(
              eq(orders.userId, account.id),
              eq(orders.productCode, "coach_30_days"),
              or(
                inArray(orders.paymentStatus, ["created", "pending", "waiting_for_capture"]),
                and(
                  eq(orders.paymentStatus, "succeeded"),
                  or(isNull(orders.creditedAt), ne(orders.fulfillmentStatus, "granted")),
                ),
              ),
            ),
          )
          .limit(1);
        if (openCoachOrder) {
          // A lost provider response can leave a real payment without a saved ID.
          // Keep the order unresolved until authoritative reconciliation.
          const [stillOpen] = await db
            .select({ id: orders.id })
            .from(orders)
            .where(
              and(
                eq(orders.userId, account.id),
                eq(orders.productCode, "coach_30_days"),
                or(
                  inArray(orders.paymentStatus, ["created", "pending", "waiting_for_capture"]),
                  and(
                    eq(orders.paymentStatus, "succeeded"),
                    or(isNull(orders.creditedAt), ne(orders.fulfillmentStatus, "granted")),
                  ),
                ),
              ),
            )
            .limit(1);
          if (stillOpen) {
            return Response.json(
              {
                code: "PAYMENT_ALREADY_IN_PROGRESS",
                error: "Для аккаунта уже открыта оплата этого тарифа. Завершите или отмените её перед новой попыткой.",
              },
              { status: 409, headers: { "Cache-Control": "no-store" } },
            );
          }
        }
      }

      if (!order) {
        const [recent] = await db
          .select({ total: count() })
          .from(orders)
          .where(
            and(
              eq(orders.userId, account.id),
              gte(orders.createdAt, sql`datetime('now', '-15 minutes')`),
            ),
          );
        if ((recent?.total ?? 0) >= 5) {
          return Response.json(
            { error: "Слишком много попыток оплаты. Повторите через 15 минут." },
            { status: 429, headers: { "Retry-After": "900", "Cache-Control": "no-store" } },
          );
        }

        const orderId = crypto.randomUUID();
        const requestHash = await billingRequestHash(expectedOrderIntegrity(orderId));
        await db
          .insert(orders)
          .values({
            id: orderId,
            userId: account.id,
            checkoutAttemptId,
            requestHash,
            providerIdempotencyKey: orderId,
            productCode: product.code,
            productVersion: product.version,
            matchId: matchId || null,
            amountKopecks: product.priceKopecks,
            currency: "RUB",
            grantAnalyses: product.analyses,
            grantCoachQuestions: product.coachQuestions,
            durationDays: product.durationDays,
            environment: runtimeIdentity.environment,
            paymentMode: runtimeIdentity.paymentMode,
            providerShopId: runtimeIdentity.providerShopId,
          })
          .onConflictDoNothing();

        [order] = await db
          .select()
          .from(orders)
          .where(eq(orders.checkoutAttemptId, checkoutAttemptId))
          .limit(1);

        if (!order && product.code === "coach_30_days") {
          return Response.json(
            {
              code: "PAYMENT_ALREADY_IN_PROGRESS",
              error: "Для аккаунта уже открыта оплата этого тарифа.",
            },
            { status: 409, headers: { "Cache-Control": "no-store" } },
          );
        }
      }
    }

    const expectedRequestHash = order
      ? await billingRequestHash(expectedOrderIntegrity(order.id))
      : null;
    if (
      !order
      || order.userId !== account.id
      || order.productCode !== product.code
      || order.productVersion !== product.version
      || order.requestHash !== expectedRequestHash
      || order.providerIdempotencyKey !== order.id
      || (product.code === "single_analysis" && order.matchId !== (matchId || null))
      || order.amountKopecks !== product.priceKopecks
      || order.currency !== "RUB"
      || order.grantAnalyses !== product.analyses
      || order.grantCoachQuestions !== product.coachQuestions
      || order.durationDays !== product.durationDays
      || order.environment !== runtimeIdentity.environment
      || order.paymentMode !== runtimeIdentity.paymentMode
      || order.provider !== "yookassa"
      || order.providerShopId !== runtimeIdentity.providerShopId
    ) {
      return Response.json(
        { error: "Эта попытка оплаты уже связана с другим заказом." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }

    const returnUrl = new URL(
      `/payment/result?order=${order.id}`,
      runtimeIdentity.appOrigin,
    ).toString();
    const payment = order.yookassaPaymentId
      ? await getYooKassaPayment(getYooKassaCredentials(), order.yookassaPaymentId)
      : await createCheckoutPayment(getYooKassaCredentials(), {
          orderId: order.id,
          productCode: product.code,
          description: `NARMA VISION — ${product.name}`,
          matchId: order.matchId || undefined,
          amountRub: yookassaAmount(product.priceKopecks),
          returnUrl,
        });

    const expectedPayment = {
      orderId: order.id,
      productCode: product.code,
      matchId: order.matchId ?? undefined,
      amountRub: yookassaAmount(order.amountKopecks),
    };
    const identityMatches = checkoutPaymentMatchesOrder(
      payment,
      expectedPayment,
      runtimeIdentity.paymentMode,
    );
    const succeededPaymentConfirmed = payment.status !== "succeeded"
      || isConfirmedCheckoutPayment(payment, expectedPayment, runtimeIdentity.paymentMode);
    const requiresManualReview = !identityMatches || !succeededPaymentConfirmed;
    // Bind the provider identity once and advance only non-terminal state. A
    // checkout retry can race a webhook after its provider GET; it must never
    // write that stale response over succeeded/canceled or granted state.
    await db.run(sql`
      UPDATE orders
      SET yookassa_payment_id = COALESCE(yookassa_payment_id, ${payment.id}),
          provider_test = COALESCE(provider_test, ${payment.test ? 1 : 0}),
          status = CASE
            WHEN status IN ('succeeded', 'canceled') OR credited_at IS NOT NULL
              THEN status
            WHEN status = 'waiting_for_capture' AND ${payment.status} = 'pending'
              THEN status
            ELSE ${payment.status}
          END,
          fulfillment_status = CASE
            WHEN fulfillment_status = 'granted' OR credited_at IS NOT NULL
              THEN fulfillment_status
            WHEN ${requiresManualReview ? 1 : 0} = 1 THEN 'manual_review'
            ELSE fulfillment_status
          END,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ${order.id}
        AND (yookassa_payment_id IS NULL OR yookassa_payment_id = ${payment.id})
        AND (provider_test IS NULL OR provider_test = ${payment.test ? 1 : 0})
    `);
    const [persistedOrder] = await db
      .select()
      .from(orders)
      .where(eq(orders.id, order.id))
      .limit(1);
    if (
      !persistedOrder
      || persistedOrder.yookassaPaymentId !== payment.id
      || persistedOrder.providerTest !== payment.test
    ) {
      throw new YooKassaError("YooKassa payment identity conflicts with the order");
    }

    if (requiresManualReview || persistedOrder.fulfillmentStatus === "manual_review") {
      throw new YooKassaError("YooKassa payment identity does not match the order");
    }

    if (persistedOrder.paymentStatus === "succeeded") {
      return Response.json(
        { error: "Этот заказ уже оплачен. Проверьте лимиты в аккаунте." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (persistedOrder.paymentStatus === "canceled") {
      return Response.json(
        { error: "Предыдущая оплата отменена. Закройте окно и выберите тариф снова." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (!["pending", "waiting_for_capture"].includes(persistedOrder.paymentStatus)) {
      throw new YooKassaError("YooKassa payment state was not persisted");
    }

    const confirmationUrl = payment.confirmation?.confirmation_url;
    if (!confirmationUrl || !confirmationUrl.startsWith("https://")) {
      throw new YooKassaError("YooKassa did not return a secure confirmation URL");
    }

    return Response.json(
      { confirmationUrl, orderId: order.id },
      { status: 201, headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("YooKassa checkout creation failed", {
      error: error instanceof Error ? error.name : "UnknownError",
    });
    const failure = paymentRouteFailure(error);
    return Response.json(
      {
        code: failure.code,
        error: "Не удалось создать оплату. Деньги не списаны — попробуйте ещё раз.",
      },
      { status: failure.status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
