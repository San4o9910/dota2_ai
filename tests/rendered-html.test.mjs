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

const developmentPreviewConfig = /["'`]codex-preview["'`]\s*:\s*["'`]development["'`]/i;

test("renders development preview metadata", async () => {
  const workerSource = await readFile(new URL("../dist/server/index.js", import.meta.url), "utf8");
  assert.match(workerSource, developmentPreviewConfig);

  const { default: NarmaAnalysis } = await vite.ssrLoadModule(
    "/components/narma/narma-analysis.tsx",
  );
  const html = renderToStaticMarkup(React.createElement(NarmaAnalysis, {
    viewer: null,
    signInHref: "/signin-with-chatgpt?return_to=%2F",
    signOutHref: "/signout-with-chatgpt?return_to=%2F",
  }));
  assert.match(html, /NARMA/);
  assert.match(html, /8963624400/);
  assert.match(html, /Драфт/);
  assert.match(html, /Лайнинг/);
  assert.match(html, /Мид-гейм/);
  assert.match(html, /Лейт-гейм/);
  assert.match(html, /src="\/maps\/7\.41\/game-map\.jpg"/);
  const image = await readFile(new URL("../dist/client/maps/7.41/game-map.jpg", import.meta.url));
  assert.equal(image.readUInt16BE(0), 0xffd8);
  assert.equal(image.length, 1048406);
  assert.match(html, /Без replay \.dem не видно/);
  assert.match(html, /href="\/pricing"/);
  assert.doesNotMatch(html, /299[^<]*₽/);
  assert.doesNotMatch(html, /799[^<]*₽/);
  assert.match(html, /\/signin-with-chatgpt\?return_to=/);
});
