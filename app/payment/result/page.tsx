import PaymentStatus from "@/components/narma/payment-status";
import { CheckCircle2, Clock3, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import {
  chatGPTSignOutPath,
  requireChatGPTUser,
} from "@/app/chatgpt-auth";
import { paymentsEnabled } from "@/lib/payments/runtime";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Статус оплаты",
  description: "Состояние оплаты тарифов NARMA VISION.",
};

const ORDER_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type PaymentResultPageProps = {
  searchParams: Promise<{ order?: string | string[] }>;
};

export default async function PaymentResultPage({ searchParams }: PaymentResultPageProps) {
  const rawOrderId = (await searchParams).order;
  const orderId = typeof rawOrderId === "string" && ORDER_ID.test(rawOrderId)
    ? rawOrderId
    : null;
  const returnTo = orderId
    ? `/payment/result?order=${encodeURIComponent(orderId)}`
    : "/payment/result";
  const user = await requireChatGPTUser(returnTo);
  const checkoutEnabled = paymentsEnabled();
  const returningFromCheckout = orderId !== null;

  return (
    <main className="payment-result-page" id="main-content" tabIndex={-1}>
      <section className="payment-result-card surface" aria-labelledby="payment-result-title">
        <span className="payment-result-icon"><ShieldCheck /></span>
        <p className="eyebrow">{returningFromCheckout ? "Возврат из ЮKassa" : "Состояние оплаты"}</p>
        <h1 id="payment-result-title">{returningFromCheckout
          ? "Статус заказа"
          : checkoutEnabled
            ? "Заказ не указан"
            : "Оплата пока закрыта"}</h1>
        <p>{returningFromCheckout
          ? "Возврат в браузер сам по себе не подтверждает оплату. NARMA принимает подтверждение только после серверной сверки с ЮKassa; откройте аккаунт, чтобы проверить доступ."
          : checkoutEnabled
            ? "Откройте оплату из карточки тарифа, чтобы она была связана с защищённым заказом."
            : "Укажите заказ, чтобы проверить его статус. В демо списаний нет."}</p>
        {orderId && <PaymentStatus id={orderId}/>}
        <div className="payment-result-steps">
          <div><CheckCircle2 /><span><strong>Аккаунт найден</strong><small>{user.displayName}</small></span></div>
          <div><Clock3 /><span><strong>{returningFromCheckout ? "Статус заказа загружается с сервера" : checkoutEnabled ? "Нет связанного заказа" : "Платёж не запущен"}</strong><small>{returningFromCheckout
            ? "Лимиты появляются только после авторитетного подтверждения провайдера."
            : "Вернитесь к тарифам: там отображается актуальная доступность оплаты."}</small></span></div>
        </div>
        <Link className="price-button" href="/account">Открыть аккаунт</Link>
        <Link className="payment-result-back" href="/">Вернуться к анализу</Link>
        <a className="payment-result-signout" href={chatGPTSignOutPath("/")} target="_top">Выйти</a>
      </section>
    </main>
  );
}
