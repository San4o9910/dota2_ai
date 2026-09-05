"use client";

import { ArrowLeft, Swords } from "lucide-react";
import Link from "next/link";

import AccountControl, { type ViewerSummary } from "@/components/narma/account-control";
import PricingSection from "@/components/narma/pricing-section";

type PricingPageProps = {
  viewer: ViewerSummary | null;
  signInHref: string;
  signOutHref: string;
  checkoutEnabled: boolean;
};

export default function PricingPage({
  viewer,
  signInHref,
  signOutHref,
  checkoutEnabled,
}: PricingPageProps) {
  return (
    <main className="narma-shell pricing-page-shell" id="main-content" tabIndex={-1}>
      <header className="topbar pricing-topbar">
        <Link className="brand" href="/" aria-label="NARMA VISION — к разбору матча">
          <span className="brand-mark"><Swords size={16} /></span>
          <span><b>NARMA</b> VISION</span>
          <small>ТАРИФЫ</small>
        </Link>
        <nav aria-label="Основная навигация">
          <Link href="/">Разбор</Link>
          <Link href="/pricing" aria-current="page">Тарифы</Link>
          {viewer && <Link href="/account">Аккаунт</Link>}
        </nav>
        <div className="topbar-actions">
          <AccountControl viewer={viewer} signInHref={signInHref} signOutHref={signOutHref} />
        </div>
      </header>

      <div className="page pricing-page-content">
        <Link className="account-back" href="/"><ArrowLeft size={17} /> Вернуться к разбору</Link>
        <PricingSection
          isAuthenticated={Boolean(viewer)}
          signInHref={signInHref}
          demoHref="/"
          checkoutEnabled={checkoutEnabled}
        />
      </div>
    </main>
  );
}
