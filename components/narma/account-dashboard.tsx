"use client";

import { ArrowLeft, CheckCircle2, Coins, LogOut, MessageCircle, Settings2, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { setEstimatedMapData, useEstimatedMapData } from "@/components/narma/use-estimated-map-data";
import type {DotaProfile} from "@/lib/dota/player-binding";

type AccountSnapshot = {
  displayName: string;
  status: string;
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
  const [dotaProfile,setDotaProfile]=useState<DotaProfile|null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const showEstimatedMapData = useEstimatedMapData();
  const accountIsActive = status === "ready" && account?.status === "active";
  const hasEntitlement = accountIsActive
    && ((account?.analysisCredits ?? 0) > 0 || (account?.coachQuestionsRemaining ?? 0) > 0);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/account/dota-player",{credentials:"same-origin",cache:"no-store",signal:controller.signal})
      .then(async response=>{if(response.ok){const data=await response.json() as {profile:DotaProfile|null};setDotaProfile(data.profile);}}).catch(()=>{});
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
        setStatus("ready");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setStatus("error");
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="account-page" id="main-content" tabIndex={-1}>
      <div className="account-page-inner">
        <Link className="account-back" href="/"><ArrowLeft size={17} /> Вернуться к разбору</Link>
        <section className="account-hero surface">
          <div>
            <p className="eyebrow">Аккаунт и настройки</p>
            <h1>Аккаунт</h1>
            <p>{displayName} · {email}</p>
          </div>
          <div className="account-security"><ShieldCheck /><span><strong>Вход через ChatGPT</strong><small>Пароль остаётся в ChatGPT. Сайт получает имя и email.</small></span></div>
        </section>

        <section className="account-plan surface">
          <div className="section-head">
            <div>
              <p className="eyebrow">Текущий доступ</p>
              <h2>{status === "loading"
                ? "Загружаем доступ…"
                : status === "error"
                  ? "Доступ временно недоступен"
                  : !accountIsActive
                    ? "Доступ приостановлен"
                    : account?.planCode === "coach_30_days"
                    ? "AI-тренер"
                    : hasEntitlement
                      ? "Доступ по лимитам"
                      : "Нет доступных лимитов"}</h2>
            </div>
            <span className={`account-status ${status}${status === "ready" && !hasEntitlement ? " suspended" : ""}`} role="status" aria-live="polite">
              {hasEntitlement && <CheckCircle2 size={15} aria-hidden="true" />}
              {status === "ready"
                ? !accountIsActive
                  ? "Приостановлен"
                  : hasEntitlement
                    ? "Доступен"
                    : "Лимит исчерпан"
                : status === "error"
                  ? "Ошибка загрузки"
                  : "Загрузка"}
            </span>
          </div>
          <div className="account-metrics">
            <div><Coins /><span><small>Полных разборов</small><strong>{status === "ready" ? account?.analysisCredits : status === "error" ? "—" : "…"}</strong></span></div>
            <div><MessageCircle /><span><small>Вопросов тренеру</small><strong>{status === "ready" ? account?.coachQuestionsRemaining : status === "error" ? "—" : "…"}</strong></span></div>
          </div>
          {status === "error" && <p className="account-page-notice" role="alert">Не удалось загрузить профиль и проверить тариф. Повторите попытку позже.</p>}
          <div className="account-page-actions">
            <Link className="price-button" href="/analyses">Мои разборы</Link>
            <Link className="price-button secondary" href="/pricing">Тарифы</Link>
            <Link className="price-button secondary" href="/">Открыть пример</Link>
          </div>
        </section>

        <section className="account-settings surface" aria-labelledby="dota-profile-title">
          <h2 id="dota-profile-title">Профиль Dota 2</h2>
          <p><strong>{dotaProfile?.nickname??"Игрок пока не закреплён"}</strong></p>
          <p>Один аккаунт платформы разбирает игру одного игрока. Герой определяется автоматически для каждого матча.</p>
          <Link className="price-button secondary" href="/analyses">{dotaProfile?"Разобрать мой матч":"Указать ник и матч"}</Link>
        </section>

        <section className="account-settings surface" aria-labelledby="account-settings-title">
          <div className="section-head">
            <div><p className="eyebrow">Настройки</p><h2 id="account-settings-title">Карта</h2></div>
            <Settings2 size={20} aria-hidden="true" />
          </div>
          <label className="account-setting-row">
            <span>
              <strong>Показывать расчётные волны крипов</strong>
              <small>Это модель, а не данные replay. По умолчанию слой выключен.</small>
            </span>
            <input
              type="checkbox"
              role="switch"
              checked={showEstimatedMapData}
              onChange={(event) => {
                setEstimatedMapData(event.target.checked);
              }}
              aria-label="Показывать расчётные волны крипов"
            />
          </label>
          <p className="account-setting-note">Настройка сохраняется только на этом устройстве.</p>
        </section>

        <a className="account-sign-out" href={signOutHref} target="_top"><LogOut size={16} /> Выйти из аккаунта</a>
      </div>
    </main>
  );
}
