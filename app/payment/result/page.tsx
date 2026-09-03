import { CheckCircle2, Clock3, ShieldCheck } from "lucide-react";
import Link from "next/link";

import {
  chatGPTSignOutPath,
  requireChatGPTUser,
} from "@/app/chatgpt-auth";

export const dynamic = "force-dynamic";

export default async function PaymentResultPage() {
  const user = await requireChatGPTUser("/payment/result");
  return (
    <main className="payment-result-page">
      <section className="payment-result-card surface">
        <span className="payment-result-icon"><Clock3 /></span>
        <p className="eyebrow">Возврат из ЮKassa</p>
        <h1>Проверяем платёж на сервере</h1>
        <p>Не закрывайте страницу оплаты до её завершения. Доступ выдаётся только после подтверждения статуса непосредственно у ЮKassa.</p>
        <div className="payment-result-steps">
          <div><CheckCircle2 /><span><strong>Аккаунт найден</strong><small>{user.displayName}</small></span></div>
          <div><ShieldCheck /><span><strong>Сумма и тариф сверяются</strong><small>Данные из браузера не используются как подтверждение.</small></span></div>
        </div>
        <Link className="price-button" href="/account">Открыть аккаунт</Link>
        <Link className="payment-result-back" href="/">Вернуться к анализу</Link>
        <a className="payment-result-signout" href={chatGPTSignOutPath("/")} target="_top">Выйти</a>
      </section>
    </main>
  );
}
