"use client";

import { ArrowLeft, CheckCircle2, Coins, LogOut, MessageCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type AccountSnapshot = {
  displayName: string;
  planCode: string;
  analysisCredits: number;
  coachQuestionsRemaining: number;
  planExpiresAt: string | null;
};

type AccountDashboardProps = {
  displayName: string;
  email: string;
  signOutHref: string;
};

export default function AccountDashboard({ displayName, email, signOutHref }: AccountDashboardProps) {
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/account", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json() as { account?: AccountSnapshot; error?: string };
        if (!response.ok || !payload.account) throw new Error(payload.error ?? "Профиль недоступен");
        setAccount(payload.account);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "Профиль временно недоступен");
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="account-page">
      <div className="account-page-inner">
        <Link className="account-back" href="/"><ArrowLeft size={17} /> Вернуться к разбору</Link>
        <section className="account-hero surface">
          <div>
            <p className="eyebrow">Аккаунт NARMA VISION</p>
            <h1>{displayName}</h1>
            <p>{email}</p>
          </div>
          <div className="account-security"><ShieldCheck /><span><strong>Вход защищён ChatGPT</strong><small>NARMA не хранит пароль и не получает доступ к вашему аккаунту.</small></span></div>
        </section>

        <section className="account-plan surface">
          <div className="section-head"><div><p className="eyebrow">Текущий доступ</p><h2>{account?.planCode === "coach_30_days" ? "AI-тренер" : "Первый разбор"}</h2></div><span className="account-status"><CheckCircle2 size={15} /> Активен</span></div>
          <div className="account-metrics">
            <div><Coins /><span><small>Полных разборов</small><strong>{account?.analysisCredits ?? (error ? "—" : "…")}</strong></span></div>
            <div><MessageCircle /><span><small>Вопросов AI-тренеру</small><strong>{account?.coachQuestionsRemaining ?? (error ? "—" : "…")}</strong></span></div>
          </div>
          {error && <p className="account-page-notice">{error}. Вход уже выполнен; данные тарифа появятся после синхронизации базы.</p>}
          <div className="account-page-actions">
            <Link className="price-button" href="/#pricing">Выбрать тариф</Link>
            <Link className="price-button secondary" href="/">Открыть анализ</Link>
          </div>
        </section>

        <section className="account-explainer surface">
          <div><span>01</span><strong>Первый вход = регистрация</strong><p>После входа NARMA создаёт отдельный профиль с бесплатным разбором.</p></div>
          <div><span>02</span><strong>История принадлежит вам</strong><p>Матчи, вопросы и прогресс связываются с защищённым идентификатором, а не с email.</p></div>
          <div><span>03</span><strong>Вход без нового пароля</strong><p>Можно завершить сеанс и снова открыть тот же профиль через защищённый вход ChatGPT.</p></div>
        </section>

        <a className="account-sign-out" href={signOutHref} target="_top"><LogOut size={16} /> Выйти из аккаунта</a>
      </div>
    </main>
  );
}
