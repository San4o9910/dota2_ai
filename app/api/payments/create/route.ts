import { and, count, eq, gte, inArray, sql } from "drizzle-orm";

import { getChatGPTUser } from "@/app/chatgpt-auth";
import { getDb } from "@/db";
import { orders } from "@/db/schema";
import {
  BILLING_CATALOG,
  isPaidProductCode,
  yookassaAmount,
} from "@/lib/billing/catalog";
import { getOrCreateCurrentAccount } from "@/lib/auth/current-account";
import {
  getYooKassaCredentials,
  paymentsEnabled,
} from "@/lib/payments/runtime";
import {
  createCheckoutPayment,
  getYooKassaPayment,
  YooKassaError,
} from "@/lib/payments/yookassa";
import { isSameOriginRequest, sameOriginError } from "@/lib/security/same-origin";
import { isJsonObject } from "@/lib/security/json";

export const dynamic = "force-dynamic";

const MATCH_ID = /^\d{8,12}$/;
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

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
    input = await request.json();
  } catch {
    return Response.json({ error: "Не удалось прочитать данные заказа." }, { status: 400 });
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
              inArray(orders.status, ["created", "pending", "waiting_for_capture"]),
            ),
          )
          .limit(1);
        if (openCoachOrder) {
          order = openCoachOrder;
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

        await db
          .insert(orders)
          .values({
            id: crypto.randomUUID(),
            userId: account.id,
            checkoutAttemptId,
            productCode: product.code,
            matchId: matchId || null,
            amountKopecks: product.priceKopecks,
          })
          .onConflictDoNothing();

        [order] = await db
          .select()
          .from(orders)
          .where(eq(orders.checkoutAttemptId, checkoutAttemptId))
          .limit(1);

        if (!order && product.code === "coach_30_days") {
          [order] = await db
            .select()
            .from(orders)
            .where(
              and(
                eq(orders.userId, account.id),
                eq(orders.productCode, "coach_30_days"),
                inArray(orders.status, ["created", "pending", "waiting_for_capture"]),
              ),
            )
            .limit(1);
        }
      }
    }

    if (
      !order
      || order.userId !== account.id
      || order.productCode !== product.code
      || (product.code === "single_analysis" && order.matchId !== (matchId || null))
      || order.amountKopecks !== product.priceKopecks
    ) {
      return Response.json(
        { error: "Эта попытка оплаты уже связана с другим заказом." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }

    const returnUrl = new URL(`/payment/result?order=${order.id}`, request.url).toString();
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

    if (payment.status === "succeeded") {
      return Response.json(
        { error: "Этот заказ уже оплачен. Проверьте лимиты в аккаунте." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }
    if (payment.status === "canceled") {
      await db
        .update(orders)
        .set({ status: "canceled", updatedAt: sql`CURRENT_TIMESTAMP` })
        .where(eq(orders.id, order.id));
      return Response.json(
        { error: "Предыдущая оплата отменена. Закройте окно и выберите тариф снова." },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      );
    }

    const confirmationUrl = payment.confirmation?.confirmation_url;
    if (!confirmationUrl || !confirmationUrl.startsWith("https://")) {
      throw new YooKassaError("YooKassa did not return a secure confirmation URL");
    }

    await db
      .update(orders)
      .set({
        status: payment.status,
        yookassaPaymentId: payment.id,
        updatedAt: sql`CURRENT_TIMESTAMP`,
      })
      .where(eq(orders.id, order.id));

    return Response.json(
      { confirmationUrl, orderId: order.id },
      { status: 201, headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    console.error("YooKassa checkout creation failed", {
      error: error instanceof Error ? error.name : "UnknownError",
    });
    const status = error instanceof YooKassaError && error.status
      ? Math.min(Math.max(error.status, 400), 599)
      : 500;
    return Response.json(
      { error: "Не удалось создать оплату. Деньги не списаны — попробуйте ещё раз." },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
