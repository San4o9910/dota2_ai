"use client";

import { ChevronDown, CircleUserRound, LogIn, LogOut, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

export type ViewerSummary = {
  displayName: string;
  email: string;
};

type AccountSnapshot = {
  displayName: string;
  status: string;
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
  const [syncState, setSyncState] = useState<"idle" | "syncing" | "ready" | "error">(
    viewer ? "syncing" : "idle",
  );
  const controlRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const avatarText = useMemo(
    () => initials(viewer?.displayName ?? "NARMA VISION"),
    [viewer?.displayName],
  );
  const accessLabel = syncState !== "ready" || !account
    ? null
    : account.status !== "active"
      ? "Аккаунт приостановлен"
      : account.planCode === "coach_30_days"
        ? "AI-тренер"
        : account.analysisCredits > 0 || account.coachQuestionsRemaining > 0
          ? "Доступ по лимитам"
          : "Лимит исчерпан";

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
        setSyncState("error");
      });
    return () => controller.abort();
  }, [viewer]);

  useEffect(() => {
    if (!open) return;
    const animationFrame = window.requestAnimationFrame(() => {
      popoverRef.current?.querySelector<HTMLElement>("a[href], button:not([disabled])")?.focus();
    });
    const closeOutside = (event: PointerEvent) => {
      if (!controlRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  if (!viewer) {
    return (
      <a className="account-sign-in" href={signInHref} target="_top">
        <LogIn size={16} />
        <span>Войти</span>
      </a>
    );
  }

  return (
    <div className="account-control" ref={controlRef}>
      <button
        ref={triggerRef}
        className="account-trigger"
        type="button"
        aria-label={`Аккаунт ${viewer.displayName}`}
        aria-expanded={open}
        aria-controls="account-popover"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="account-avatar" aria-hidden="true">{avatarText}</span>
        <span className="account-trigger-copy">
          <strong>{viewer.displayName}</strong>
          <small>{syncState === "syncing"
            ? "Загрузка профиля"
            : syncState === "error"
              ? "Профиль недоступен"
              : accessLabel}</small>
        </span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>

      {open && (
        <div className="account-popover" id="account-popover" ref={popoverRef} role="region" aria-label="Аккаунт">
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

          <p className={`account-sync ${syncState}`} role="status" aria-live="polite">
            <ShieldCheck size={14} aria-hidden="true" />
            {syncState === "ready"
              ? account?.status === "active"
                ? "Профиль NARMA защищён и синхронизирован"
                : "Профиль синхронизирован; доступ приостановлен"
              : syncState === "error"
                ? "Не удалось загрузить профиль. Повторите позже."
                : "Создаём профиль NARMA…"}
          </p>

          <nav aria-label="Действия аккаунта">
            <Link className="account-menu-link" href="/account" onClick={() => setOpen(false)}>
              <CircleUserRound size={16} /> Аккаунт и настройки
            </Link>
            <a className="account-menu-link danger" href={signOutHref} target="_top">
              <LogOut size={16} /> Выйти
            </a>
          </nav>
        </div>
      )}
    </div>
  );
}
