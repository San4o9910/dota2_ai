import assert from "node:assert/strict";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

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

test("first match fixture preserves the complete top-level evidence contract", async () => {
  const data = await vite.ssrLoadModule("/app/data/match-8963624400.ts");

  assert.equal(data.MATCH.id, 8963624400);
  assert.equal(data.MATCH.duration, 2829);
  assert.equal(data.HEROES.length, 10);
  assert.equal(data.STAGES.length, 4);
  assert.equal(data.AXES.length, 5);
  assert.equal(data.GOLD_ADV.length, 48);
  assert.equal(data.XP_ADV.length, 48);
  assert.equal(data.FIGHTS.length, 15);
  assert.equal(data.WARDS.length, 114);
  assert.equal(data.HEROES.reduce((sum, hero) => sum + hero.wards, 0), 41);
  assert.equal(data.HEROES.reduce((sum, hero) => sum + hero.sentries, 0), 73);
});

test("map fixture exposes every requested Dota object class", async () => {
  const { MAP_OBJECTS } = await vite.ssrLoadModule("/app/data/match-8963624400.ts");
  const kinds = new Set(MAP_OBJECTS.map((object) => object.kind));

  for (const kind of ["roshan", "tormentor", "wisdom", "lotus", "gate", "watcher", "outpost", "shop", "tower", "ancient", "camp", "bounty", "power"]) {
    assert.ok(kinds.has(kind), `missing map object kind: ${kind}`);
  }
});

test("the decisive 43:06 fight is encoded without reversing deaths", async () => {
  const { FIGHTS, EVENTS } = await vite.ssrLoadModule("/app/data/match-8963624400.ts");
  const fight = FIGHTS.find((item) => item.start === 2586);

  assert.ok(fight);
  assert.equal(fight.radiant.kills, 0);
  assert.equal(fight.radiant.deaths, 3);
  assert.equal(fight.dire.kills, 3);
  assert.equal(fight.dire.deaths, 0);
  assert.ok(EVENTS.some((event) => event.t === 2586 && /3×4/.test(event.title)));
});
