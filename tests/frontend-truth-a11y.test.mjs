import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

after(async () => vite.close());

test("server-rendered demo separates pricing and states its data limits", async () => {
  const [{ default: NarmaAnalysis }, { default: PricingSection }] = await Promise.all([
    vite.ssrLoadModule("/components/narma/narma-analysis.tsx"),
    vite.ssrLoadModule("/components/narma/pricing-section.tsx"),
  ]);
  const html = renderToStaticMarkup(React.createElement(NarmaAnalysis, {
    viewer: null,
    signInHref: "/signin-with-chatgpt?return_to=%2F",
    signOutHref: "/signout-with-chatgpt?return_to=%2F",
  }));
  const pricingHtml = renderToStaticMarkup(React.createElement(PricingSection, {
    isAuthenticated: false,
    signInHref: "/signin-with-chatgpt?return_to=%2Fpricing",
    demoHref: "/",
    checkoutEnabled: false,
  }));

  assert.match(html, /<main[^>]+id="main-content"[^>]+tabindex="-1"/);
  assert.doesNotMatch(html, /aria-current="location"/);
  assert.match(html, /href="\/pricing"/);
  assert.doesNotMatch(html, /id="pricing"/);
  assert.match(html, /<img[^>]+src="\/maps\/7\.41\/game-map\.jpg"[^>]+alt="Игровая карта Dota 2, патч 7.41"/);
  assert.match(html, /Без replay \.dem не видно/);
  assert.match(html, /Пример разбора · Juggernaut/);
  assert.match(html, /интерпретация/);
  assert.match(html, /Туман войны недоступен в сводке/);
  assert.match(html, /role="region" aria-label="Прокручиваемый график[^<]+" tabindex="0"/);
  assert.match(html, /Gold \+ XP · одна шкала/);
  assert.match(html, /Общая шкала · Radiant выше нуля, Dire ниже/);
  assert.match(html, /Gold · срез 7:00/);
  assert.match(html, /XP · срез 7:00/);
  assert.doesNotMatch(html, /<small>Источник<\/small>/);
  assert.match(pricingHtml, /Оплата отключена/);
  assert.match(pricingHtml, /Что войдёт:/);
  assert.match(pricingHtml, /<button[^>]+disabled=""[^>]+aria-describedby="payment-availability"[^>]*>Скоро/);
  assert.match(pricingHtml, /Новые Match ID пока не принимаются/);
  assert.doesNotMatch(html, /кредит возвращается автоматически/i);
  assert.doesNotMatch(html, /5[–-]10 минут/i);
});

test("account-bound Scan SSR starts with a bounded Match ID form and factual copy", async () => {
  const { default: NarmaScanFlow } = await vite.ssrLoadModule(
    "/components/narma/narma-scan-flow.tsx",
  );
  const html = renderToStaticMarkup(React.createElement(NarmaScanFlow));

  assert.match(html, /Ник в Dota 2/);
  assert.match(html, /<form[^>]+aria-busy="false"/);
  assert.match(html, /id="scan-match-id"/);
  assert.match(html, /inputMode="numeric"/);
  assert.match(html, /maxLength="12"/);
  assert.match(html, /Персональный разбор закрепляется за одним игроком/);
  assert.match(html, /role="status" aria-live="polite" aria-atomic="true"/);
  assert.doesNotMatch(html, /кредит|оплат|модель/i);
  assert.doesNotMatch(html, /только демонстрационн/i);
});

test("account SSR never presents a default plan before the profile loads", async () => {
  const [{ default: AccountControl }, { default: AccountDashboard }] = await Promise.all([
    vite.ssrLoadModule("/components/narma/account-control.tsx"),
    vite.ssrLoadModule("/components/narma/account-dashboard.tsx"),
  ]);
  const viewer = { displayName: "Тестовый игрок", email: "player@example.test" };
  const controlHtml = renderToStaticMarkup(React.createElement(AccountControl, {
    viewer,
    signInHref: "/signin",
    signOutHref: "/signout",
  }));
  const dashboardHtml = renderToStaticMarkup(React.createElement(AccountDashboard, {
    ...viewer,
    signOutHref: "/signout",
  }));

  assert.match(controlHtml, /aria-label="Аккаунт Тестовый игрок"/);
  assert.match(controlHtml, /aria-controls="account-popover"/);
  assert.match(controlHtml, /Загрузка профиля/);
  assert.doesNotMatch(controlHtml, /Пробный доступ/);
  assert.match(dashboardHtml, /Загружаем доступ/);
  assert.match(dashboardHtml, /id="main-content"/);
  assert.match(dashboardHtml, /Аккаунт и настройки/);
  assert.match(dashboardHtml, /role="switch"/);
  assert.doesNotMatch(dashboardHtml, />Активен</);
  assert.doesNotMatch(dashboardHtml, />Первый разбор</);
});

test("dialog and account source contracts include keyboard and focus behavior", async () => {
  const [analysis, scanFlow, pricing, dialogHook, account] = await Promise.all([
    readFile(new URL("../components/narma/narma-analysis.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/narma/narma-scan-flow.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/narma/pricing-section.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/narma/use-modal-dialog.ts", import.meta.url), "utf8"),
    readFile(new URL("../components/narma/account-control.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(analysis, /role="dialog"/);
  assert.match(analysis, /aria-modal="true"/);
  assert.match(analysis, /aria-labelledby="match-dialog-title"/);
  assert.match(analysis, /aria-describedby="match-dialog-description"/);
  assert.match(analysis, /id="match-id-error" role="alert"/);
  assert.match(analysis, /event\.target === event\.currentTarget/);
  assert.match(analysis, /currentTimelineEvent === event/);
  assert.match(analysis, /scanEnabled \? \(/);
  assert.doesNotMatch(analysis, /question\.includes\(|setMessages\(/);
  assert.match(analysis, /href="\/replays"/);
  assert.doesNotMatch(analysis, /Black Hole|BKB|Blink|Requiem|Eclipse/);
  assert.match(scanFlow, /new AbortController\(\)/);
  assert.match(scanFlow, /controller\.current\?\.abort\(\)/);
  assert.match(scanFlow, /fetch\("\/api\/scan"/);
  assert.match(scanFlow, /credentials:\s*"same-origin"/);
  assert.match(scanFlow, /aria-live="polite"/);
  assert.doesNotMatch(scanFlow, /scan-roster|Другая перспектива/);
  assert.match(scanFlow,/PlayerIdentityPanel/);
  assert.match(scanFlow, /не установленная причина поражения/);
  assert.match(scanFlow, /JSON.stringify\(\{matchId\}\)/);
  assert.doesNotMatch(analysis, /onMouseDown=/);
  assert.match(pricing, /aria-describedby="checkout-description"/);
  assert.match(pricing, /data-dialog-initial-focus/);
  assert.match(pricing, /id="checkout-error" role="alert"/);
  assert.match(dialogHook, /event\.key === "Escape"/);
  assert.match(dialogHook, /event\.key !== "Tab"/);
  assert.match(dialogHook, /returnTarget\?\.isConnected/);
  assert.match(account, /document\.addEventListener\("pointerdown", closeOutside\)/);
  assert.match(account, /event\.key !== "Escape"/);
  assert.match(account, /triggerRef\.current\?\.focus\(\)/);
  assert.match(account, /role="status" aria-live="polite"/);
  assert.match(account, /account\.status !== "active"/);
  assert.match(account, /Лимит исчерпан/);
});

test("layout and routes expose generic metadata, skip navigation, and truthful payment copy", async () => {
  const [layout, homePage, accountPage, paymentPage, css] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/account/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/payment/result/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(layout, /template: "%s \| NARMA VISION"/);
  assert.match(layout, /className="skip-link" href="#main-content"/);
  assert.doesNotMatch(layout, /title:\s*"[^\n]*8963624400/);
  assert.match(homePage, /scanEnabled=\{scanRuntimeEnabled\(\)\}/);
  assert.match(accountPage, /export const metadata: Metadata/);
  assert.match(paymentPage, /export const metadata: Metadata/);
  assert.match(paymentPage, /Оплата пока закрыта/);
  assert.match(paymentPage, /orderId && <PaymentStatus/);
  assert.match(paymentPage, /returningFromCheckout = orderId !== null/);
  assert.match(paymentPage, /Статус заказа/);
  assert.match(paymentPage, /Возврат в браузер сам по себе не подтверждает оплату/);
  assert.doesNotMatch(paymentPage, /Проверяем платёж/);
  assert.match(css, /\.skip-link:focus/);
  assert.match(css, /100dvh/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /overscroll-behavior-inline:\s*contain/);
  assert.match(css, /\.chart-legend\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
  assert.match(css, /\.stage-kpis\s*\{[^}]*grid-template-columns:\s*repeat\(2,/);
  assert.doesNotMatch(css, /softGlow|goldGlow/);
});
