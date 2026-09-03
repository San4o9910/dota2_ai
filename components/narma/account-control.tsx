"use client";

import { ChevronDown, CircleUserRound, LogIn, LogOut, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

export type ViewerSummary = {
  displayName: string;
  email: string;
};

type AccountSnapshot = {
  displayName: string;
  planCode: string;
  analysisCredits: number;
  coachQuestionsRemaining: number;
  planExpiresAt: string | null;
};

type AccountControlProps = {
  viewer: ViewerSummary | null;
  signInHref: string;
  signOutHref: string;
};

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toLocaleUpperCase("ru-RU") ?? "")
    .join("") || "NV";
}

export default function AccountControl({
  viewer,
  signInHref,
  signOutHref,
}: AccountControlProps) {
  const [open, setOpen] = useState(false);
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [syncState, setSyncState] = useState<"idle" | "syncing" | "ready" | "delayed">(
    viewer ? "syncing" : "idle",
  );
  const avatarText = useMemo(
    () => initials(viewer?.displayName ?? "NARMA VISION"),
    [viewer?.displayName],
  );

  useEffect(() => {
    if (!viewer) return;
    const controller = new AbortController();
    fetch("/api/account", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json() as { account?: AccountSnapshot; error?: string };
        if (!response.ok || !payload.account) throw new Error(payload.error ?? "Account unavailable");
        setAccount(payload.account);
        setSyncState("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSyncState("delayed");
      });
    return () => controller.abort();
  }, [viewer]);

  if (!viewer) {
    return (
      <a className="account-sign-in" href={signInHref} target="_top">
        <LogIn size={16} />
        <span>Войти</span>
      </a>
    );
  }

  return (
    <div className="account-control">
      <button
        className="account-trigger"
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="account-avatar" aria-hidden="true">{avatarText}</span>
        <span className="account-trigger-copy">
          <strong>{viewer.displayName}</strong>
          <small>{account?.planCode === "coach_30_days" ? "AI-тренер" : "Пробный доступ"}</small>
        </span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="account-popover" role="menu">
          <div className="account-identity">
            <span className="account-avatar large" aria-hidden="true">{avatarText}</span>
            <div>
              <strong>{viewer.displayName}</strong>
              <span>{viewer.email}</span>
            </div>
          </div>

          <div className="account-entitlements">
            <div>
              <small>Разборов доступно</small>
              <strong>{account?.analysisCredits ?? (syncState === "syncing" ? "…" : "—")}</strong>
            </div>
            <div>
              <small>Вопросов тренеру</small>
              <strong>{account?.coachQuestionsRemaining ?? (syncState === "syncing" ? "…" : "—")}</strong>
            </div>
          </div>

          <p className={`account-sync ${syncState}`}>
            <ShieldCheck size={14} />
            {syncState === "ready"
              ? "Профиль NARMA защищён и синхронизирован"
              : syncState === "delayed"
                ? "Вход выполнен; профиль будет синхронизирован после подключения базы"
                : "Создаём профиль NARMA…"}
          </p>

          <Link className="account-menu-link" href="/account" onClick={() => setOpen(false)} role="menuitem">
            <CircleUserRound size={16} /> Мой аккаунт
          </Link>
          <a className="account-menu-link danger" href={signOutHref} target="_top" role="menuitem">
            <LogOut size={16} /> Выйти
          </a>
        </div>
      )}
    </div>
  );
}
