"use client";

import {
  CheckCircle2,
  Clock3,
  CreditCard,
  Gauge,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { FormEvent, useState } from "react";

import {
  BILLING_CATALOG,
  FREE_TRIAL,
  formatRubles,
  type BillingProduct,
  type PaidProductCode,
} from "@/lib/billing/catalog";

type PricingSectionProps = {
  isAuthenticated: boolean;
  signInHref: string;
  onStartTrial: () => void;
};

export default function PricingSection({
  isAuthenticated,
  signInHref,
  onStartTrial,
}: PricingSectionProps) {
  const [selected, setSelected] = useState<BillingProduct | null>(null);
  const [matchId, setMatchId] = useState("");
  const [checkoutAttemptId, setCheckoutAttemptId] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  const choose = (code: PaidProductCode) => {
    setSelected(BILLING_CATALOG[code]);
    setMatchId("");
    setCheckoutAttemptId(crypto.randomUUID());
    setNotice("");
  };

  const submitCheckout = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected || loading) return;
    setLoading(true);
    setNotice("");
    try {
      const response = await fetch("/api/payments/create", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ productCode: selected.code, matchId, checkoutAttemptId }),
      });
      const payload = await response.json() as { confirmationUrl?: string; error?: string };
      if (!response.ok || !payload.confirmationUrl) {
        setNotice(payload.error ?? "Не удалось создать оплату. Деньги не списаны.");
        return;
      }
      window.location.assign(payload.confirmationUrl);
    } catch {
      setNotice("Нет связи с оплатой. Деньги не списаны — попробуйте позднее.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="pricing-section" id="pricing">
      <div className="pricing-heading">
        <div>
          <p className="eyebrow">Понятная цена без безлимита</p>
          <h2>Начните бесплатно, платите только за полезные разборы</h2>
          <p>Полный анализ обычно готовится 5–10 минут. Повторное открытие того же отчёта не расходует кредит.</p>
        </div>
        <div className="payment-state">
          <ShieldCheck size={18} />
          <span><strong>ЮKassa подготовлена</strong><small>Сейчас тестовый режим · списаний нет</small></span>
        </div>
      </div>

      <div className="pricing-grid">
        <article className="price-card surface trial">
          <div className="price-card-top">
            <span className="price-icon"><Sparkles size={20} /></span>
            <small>Знакомство с продуктом</small>
          </div>
          <h3>{FREE_TRIAL.name}</h3>
          <div className="price"><strong>0 ₽</strong><span>один раз</span></div>
          <p>{FREE_TRIAL.description}</p>
          <ul>
            <li><CheckCircle2 />Все четыре стадии игры</li>
            <li><CheckCircle2 />Интерактивная карта и диаграммы</li>
            <li><CheckCircle2 />{FREE_TRIAL.coachQuestions} вопросов AI-тренеру</li>
          </ul>
          {isAuthenticated ? (
            <button type="button" className="price-button secondary" onClick={onStartTrial}>Начать бесплатный разбор</button>
          ) : (
            <a className="price-button secondary" href={signInHref} target="_top">Создать аккаунт</a>
          )}
          <small className="price-note">Одна бесплатная проба на аккаунт</small>
        </article>

        {Object.values(BILLING_CATALOG).map((product) => (
          <article key={product.code} className={`price-card surface ${product.code === "coach_30_days" ? "featured" : ""}`}>
            {product.code === "coach_30_days" && <span className="recommended">Выгоднее с 3-го матча</span>}
            <div className="price-card-top">
              <span className="price-icon">{product.code === "coach_30_days" ? <Gauge size={20} /> : <CreditCard size={20} />}</span>
              <small>{product.shortName}</small>
            </div>
            <h3>{product.name}</h3>
            <div className="price"><strong>{formatRubles(product.priceKopecks)}</strong><span>{product.durationDays ? "/ 30 дней" : "за матч"}</span></div>
            <p>{product.description}</p>
            <ul>
              {product.features.map((feature) => <li key={feature}><CheckCircle2 />{feature}</li>)}
            </ul>
            {isAuthenticated ? (
              <button type="button" className="price-button" onClick={() => choose(product.code)}>Выбрать тариф</button>
            ) : (
              <a className="price-button" href={signInHref} target="_top">Войти и выбрать</a>
            )}
            <small className="price-note">Без автопродления · неиспользованные лимиты не переносятся</small>
          </article>
        ))}
      </div>

      <div className="pricing-rules surface">
        <div><Clock3 /><span><strong>Контроль времени</strong><small>Если анализ не готов за 30 минут из-за сервиса, кредит возвращается автоматически.</small></span></div>
        <div><ShieldCheck /><span><strong>Оплата после оформления продавца</strong><small>На российском запуске — рубли через ЮKassa. Крипта и скины как оплата не принимаются.</small></span></div>
        <div><Gauge /><span><strong>Честный лимит</strong><small>8 полных разборов — тренировочный ритм два раза в неделю без скрытого ограничения нейросети.</small></span></div>
      </div>

      {selected && (
        <div
          className="checkout-modal"
          role="presentation"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}
          onKeyDown={(event) => { if (event.key === "Escape") setSelected(null); }}
        >
          <form
            className="checkout-dialog surface"
            role="dialog"
            aria-modal="true"
            aria-labelledby="checkout-title"
            onSubmit={submitCheckout}
          >
            <button type="button" className="dialog-close" onClick={() => setSelected(null)} aria-label="Закрыть"><X size={20} /></button>
            <p className="eyebrow">Безопасная оплата</p>
            <h2 id="checkout-title">{selected.name}</h2>
            <div className="checkout-price"><strong>{formatRubles(selected.priceKopecks)}</strong><span>{selected.analyses} {selected.analyses === 1 ? "разбор" : "разборов"}</span></div>
            <label>
              <span>{selected.code === "single_analysis" ? "Match ID для разбора" : "Match ID первого матча (необязательно)"}</span>
              <input
                autoFocus
                inputMode="numeric"
                value={matchId}
                onChange={(event) => { setMatchId(event.target.value.replace(/\D/g, "").slice(0, 12)); setNotice(""); }}
                placeholder="8963624400"
                required={selected.code === "single_analysis"}
              />
            </label>
            <div className="checkout-provider"><CreditCard size={17} /><span><strong>ЮKassa</strong><small>Доступные карты и способы оплаты будут показаны на защищённой странице провайдера.</small></span></div>
            <div className="checkout-warning"><ShieldCheck size={16} /><span>Тестовый режим: пока вы не оформите самозанятость и не добавите ключи магазина, форма не создаст реальное списание.</span></div>
            {notice && <div className="checkout-notice" role="status">{notice}</div>}
            <button className="checkout-submit" type="submit" disabled={loading}>{loading ? "Проверяем…" : "Перейти к ЮKassa"}</button>
            <small className="checkout-legal">Цена и состав тарифа задаются сервером. Кредит списывается только после успешно готового анализа.</small>
          </form>
        </div>
      )}
    </section>
  );
}
