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
import Link from "next/link";
import { FormEvent, useCallback, useRef, useState } from "react";

import { useModalDialog } from "@/components/narma/use-modal-dialog";
import {
  BILLING_CATALOG,
  formatRubles,
  type BillingProduct,
  type PaidProductCode,
} from "@/lib/billing/catalog";

type PricingSectionProps = {
  isAuthenticated: boolean;
  signInHref: string;
  demoHref: string;
  checkoutEnabled: boolean;
};

export default function PricingSection({
  isAuthenticated,
  signInHref,
  demoHref,
  checkoutEnabled,
}: PricingSectionProps) {
  const [selected, setSelected] = useState<BillingProduct | null>(null);
  const [matchId, setMatchId] = useState("");
  const [checkoutAttemptId, setCheckoutAttemptId] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const checkoutDialogRef = useRef<HTMLFormElement>(null);
  const checkoutReturnFocusRef = useRef<HTMLElement | null>(null);

  const closeCheckout = useCallback(() => {
    setSelected(null);
    setNotice("");
  }, []);

  useModalDialog(Boolean(selected), checkoutDialogRef, checkoutReturnFocusRef, closeCheckout);

  const choose = (code: PaidProductCode) => {
    if (!checkoutEnabled) return;
    checkoutReturnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
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
          <p className="eyebrow">Тарифы</p>
          <h2>{checkoutEnabled ? "Разбор за 299 ₽ или 30 дней за 799 ₽" : "Платные разборы ещё не открыты"}</h2>
          <p>{checkoutEnabled
            ? "Выберите один матч или пакет на 30 дней. Перед оплатой потребуется войти."
            : "Сейчас можно посмотреть один готовый разбор. Когда приём новых матчей заработает, здесь появится оплата."}</p>
        </div>
        <div className="payment-state" id="payment-availability" role="status" aria-live="polite">
          <ShieldCheck size={18} />
          <span>
            <strong>{checkoutEnabled ? "Оплата доступна" : "Оплата отключена"}</strong>
            <small>{checkoutEnabled ? "Переход к ЮKassa откроется после выбора" : "Сайт не откроет платёжную форму"}</small>
          </span>
        </div>
      </div>

      <div className="pricing-grid">
        <article className="price-card surface trial">
          <div className="price-card-top">
            <span className="price-icon"><Sparkles size={20} /></span>
            <small>Сейчас доступно</small>
          </div>
          <h3>Пример разбора</h3>
          <div className="price"><strong>0 ₽</strong><span>без регистрации</span></div>
          <p>Готовый матч 8963624400: факты, карта, таймлайн и тренировка.</p>
          <ul>
            <li><CheckCircle2 />Карта и события матча</li>
            <li><CheckCircle2 />Экономика и драки</li>
            <li><CheckCircle2 />Вопросы по готовым данным</li>
          </ul>
          <Link className="price-button secondary" href={demoHref}>Открыть пример</Link>
          <small className="price-note">Новые Match ID пока не принимаются</small>
        </article>

        {Object.values(BILLING_CATALOG).map((product) => (
          <article key={product.code} className={`price-card surface ${product.code === "coach_30_days" ? "featured" : ""}`}>
            {product.code === "coach_30_days" && <span className="recommended">Выгоднее с 3-го матча</span>}
            <div className="price-card-top">
              <span className="price-icon">{product.code === "coach_30_days" ? <Gauge size={20} /> : <CreditCard size={20} />}</span>
              <small>{checkoutEnabled ? product.shortName : "Скоро"}</small>
            </div>
            <h3>{product.name}</h3>
            <div className="price"><strong>{formatRubles(product.priceKopecks)}</strong><span>{product.durationDays ? "/ 30 дней" : "за матч"}</span></div>
            <p>{product.description}</p>
            {!checkoutEnabled && <small className="planned-label">Что войдёт:</small>}
            <ul>
              {product.features.map((feature) => <li key={feature}><CheckCircle2 />{feature}</li>)}
            </ul>
            {!checkoutEnabled ? (
              <button type="button" className="price-button" disabled aria-describedby="payment-availability">Скоро</button>
            ) : isAuthenticated ? (
              <button type="button" className="price-button" onClick={() => choose(product.code)}>Выбрать тариф</button>
            ) : (
              <a className="price-button" href={signInHref} target="_top">Войти и выбрать</a>
            )}
            <small className="price-note">{checkoutEnabled ? "Без автопродления · неиспользованные лимиты не переносятся" : "Оплата не подключена"}</small>
          </article>
        ))}
      </div>

      <div className="pricing-rules surface">
        <div><Clock3 /><span><strong>Сейчас — один пример</strong><small>Новые матчи пока не отправляются на анализ.</small></span></div>
        <div><ShieldCheck /><span><strong>Без списаний</strong><small>Пока оплата отключена, платёжная форма не открывается.</small></span></div>
        <div><Gauge /><span><strong>Лимиты видны заранее</strong><small>Количество разборов и вопросов указано в карточках.</small></span></div>
      </div>

      {selected && (
        <div
          className="checkout-modal"
          role="presentation"
          onClick={(event) => { if (event.target === event.currentTarget) closeCheckout(); }}
        >
          <form
            ref={checkoutDialogRef}
            className="checkout-dialog surface"
            role="dialog"
            aria-modal="true"
            aria-labelledby="checkout-title"
            aria-describedby="checkout-description"
            tabIndex={-1}
            onSubmit={submitCheckout}
          >
            <button type="button" className="dialog-close" onClick={closeCheckout} aria-label="Закрыть оформление тарифа"><X size={20} /></button>
            <p className="eyebrow">Безопасная оплата</p>
            <h2 id="checkout-title">{selected.name}</h2>
            <p id="checkout-description" className="checkout-description">Проверьте Match ID перед переходом на защищённую страницу платёжного провайдера.</p>
            <div className="checkout-price"><strong>{formatRubles(selected.priceKopecks)}</strong><span>{selected.analyses} {selected.analyses === 1 ? "разбор" : "разборов"}</span></div>
            <label htmlFor="checkout-match-id">
              <span>{selected.code === "single_analysis" ? "Match ID для разбора" : "Match ID первого матча (необязательно)"}</span>
              <input
                id="checkout-match-id"
                name="matchId"
                data-dialog-initial-focus
                inputMode="numeric"
                value={matchId}
                onChange={(event) => { setMatchId(event.target.value.replace(/\D/g, "").slice(0, 12)); setNotice(""); }}
                placeholder="8963624400"
                required={selected.code === "single_analysis"}
                aria-describedby="checkout-description"
              />
            </label>
            <div className="checkout-provider"><CreditCard size={17} /><span><strong>ЮKassa</strong><small>Доступные карты и способы оплаты будут показаны на защищённой странице провайдера.</small></span></div>
            <div className="checkout-warning"><ShieldCheck size={16} /><span>Цена и тариф повторно проверяются сервером; подтверждение оплаты принимается только от ЮKassa.</span></div>
            {notice && <div className="checkout-notice" id="checkout-error" role="alert">{notice}</div>}
            <button className="checkout-submit" type="submit" disabled={loading}>{loading ? "Проверяем…" : "Перейти к ЮKassa"}</button>
            <small className="checkout-legal">Цена и состав тарифа задаются сервером. Возврат на эту страницу сам по себе не подтверждает выдачу доступа.</small>
          </form>
        </div>
      )}
    </section>
  );
}
