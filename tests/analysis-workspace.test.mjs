import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { createAnalysisVite } from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

test("analysis workspace renders a labeled, gated form and truthful empty state", async () => {
  const { default: AnalysisWorkspace } = await vite.ssrLoadModule(
    "/components/narma/analysis-workspace.tsx",
  );
  const html = renderToStaticMarkup(React.createElement(AnalysisWorkspace, {
    acceptingJobs: false,
    fulfillmentReady: false,
  }));

  assert.match(html, /<main[^>]+id="main-content"[^>]+tabindex="-1"/);
  assert.match(html, /<label for="full-analysis-match-id">Match ID<\/label>/);
  assert.match(html, /id="full-analysis-match-id"/);
  assert.match(html, /inputMode="numeric"/);
  assert.match(html, /maxLength="12"/);
  assert.match(html, /<label for="full-analysis-player">Ваш герой<\/label>/);
  assert.match(html, /<button type="submit" disabled=""/);
  assert.match(html, /Новые разборы пока недоступны/);
  assert.match(html, /Выберите героя из матча/);
  assert.doesNotMatch(html, /анализируется прямо сейчас|оплата подтверждена/i);
});

test("analysis workspace source keeps owner APIs same-origin and numeric UI claim-driven", async () => {
  const source = await readFile(
    new URL("../components/narma/analysis-workspace.tsx", import.meta.url),
    "utf8",
  );
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

  assert.match(source, /fetch\("\/api\/analyses"/);
  assert.match(source, /credentials: "same-origin"/);
  assert.match(source, /"Idempotency-Key": crypto\.randomUUID\(\)/);
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /Отменить и вернуть резерв/);
  assert.match(source, /response\.headers\.get\("Retry-After"\)/);
  assert.match(source, /Проверить и восстановить/);
  assert.match(source, /Проверить тайм-аут и отменить/);
  assert.match(source, /AnalysisDetailSchema\.parse/);
  assert.match(source, /claimRows\(item\)/);
  assert.match(source, /Цифры сверены с данными матча/);
  assert.match(source, /<strong>Чего здесь не видно<\/strong>/);
  assert.match(source, /<details className="analysis-evidence">/);
  assert.doesNotMatch(source, /Отчёт прошёл schema|evidence hash|reference validation/);
  assert.match(source, /aria-live="polite"/);
  assert.match(css, /\.analysis-create form > button[\s\S]+min-height:\s*48px/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
