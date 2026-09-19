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

test("public demo is explicitly fictional and internally consistent", async () => {
  const data = await vite.ssrLoadModule("/app/data/demo-match.ts");
  assert.equal(data.MATCH.id, "training-example");
  assert.match(data.MATCH.source, /Вымышленные/);
  assert.equal(data.HEROES.length, 10);
  assert.equal(new Set(data.HEROES.map(hero => hero.id)).size, 10);
  assert.ok(data.HEROES.every(hero => /^Учебный игрок \d+$/.test(hero.player)));
  assert.equal(data.GOLD_ADV.length, data.MATCH.duration / 60 + 1);
  assert.equal(data.XP_ADV.length, data.GOLD_ADV.length);
  assert.equal(data.HEROES.filter(h => h.side === "R").reduce((n,h) => n+h.kills,0), data.MATCH.score.radiant);
  assert.equal(data.HEROES.filter(h => h.side === "D").reduce((n,h) => n+h.deaths,0), data.MATCH.score.radiant);
  assert.equal(data.HEROES.filter(h => h.side === "D").reduce((n,h) => n+h.kills,0), data.MATCH.score.dire);
  assert.equal(data.HEROES.filter(h => h.side === "R").reduce((n,h) => n+h.deaths,0), data.MATCH.score.dire);
  for (const hero of data.HEROES) {
    assert.equal(data.WARDS.filter(w => w.heroId === hero.id && w.type === "obs").length, hero.wards);
    assert.equal(data.WARDS.filter(w => w.heroId === hero.id && w.type === "sen").length, hero.sentries);
  }
  assert.ok(data.WARDS.every(w => w.t <= data.MATCH.duration && data.HEROES.some(h => h.id === w.heroId && h.side === w.side)));
});

test("map fixture exposes every requested Dota object class", async () => {
  const { MAP_OBJECTS } = await vite.ssrLoadModule("/app/data/demo-match.ts");
  const kinds = new Set(MAP_OBJECTS.map((object) => object.kind));

  for (const kind of ["roshan", "tormentor", "wisdom", "lotus", "gate", "watcher", "outpost", "shop", "tower", "ancient", "camp", "bounty", "power"]) {
    assert.ok(kinds.has(kind), `missing map object kind: ${kind}`);
  }
});

test("authored fight evidence agrees with participants and timeline", async () => {
  const { FIGHTS, EVENTS, MATCH, HEROES } = await vite.ssrLoadModule("/app/data/demo-match.ts");
  for (const fight of FIGHTS) {
    assert.ok(fight.start < fight.end && fight.end <= MATCH.duration);
    assert.equal(fight.radiant.kills, fight.dire.deaths);
    assert.equal(fight.dire.kills, fight.radiant.deaths);
    assert.equal(fight.deaths.filter(p => p.side === "R").length, fight.radiant.deaths);
    assert.equal(fight.deaths.filter(p => p.side === "D").length, fight.dire.deaths);
    assert.ok(fight.deaths.every(p => HEROES.some(h => h.id === p.heroId && h.side === p.side)));
    assert.ok(EVENTS.some(event => event.t === fight.start && event.type === "fight"));
  }
});

test("training plan covers every stage and every analysis axis", async () => {
  const { MATCH } = await vite.ssrLoadModule("/app/data/demo-match.ts");
  const { TRAINING_PLAN } = await vite.ssrLoadModule("/components/narma/narma-analysis.tsx");
  const stages = Object.entries(TRAINING_PLAN);
  const drills = stages.flatMap(([, stage]) => stage.drills);

  assert.equal(stages.length, 4);
  assert.equal(drills.length, 8);
  for (const [stageKey, stage] of stages) {
    assert.equal(stage.drills.length, 2, `${stageKey} must have exactly two focused drills`);
    assert.ok(stage.goal.length > 20);
    assert.ok(stage.result.length > 20);
  }

  for (const drill of drills) {
    assert.ok(drill.reflectionQuestion.length > 20);
    assert.ok(drill.reflectionQuestion.endsWith("?"));
    assert.ok(drill.decisionRule.length > 40);
    assert.ok(drill.why.length > 40);
    assert.ok(drill.evidence.length > 30);
    assert.ok(drill.steps.length >= 3);
    assert.ok(drill.metric.length > 20);
    assert.ok(drill.dose.length > 5);
    assert.ok(drill.moment >= 0 && drill.moment <= MATCH.duration);
  }

  const axes = drills.map((drill) => drill.axis.toLowerCase()).join(" ");
  for (const axis of ["передвижения", "вижен", "ресурсы", "макро", "микро"]) {
    assert.match(axes, new RegExp(axis));
  }
});

test("demo coaching copy does not invent replay-only mechanics", async () => {
  const data = await vite.ssrLoadModule("/app/data/demo-match.ts");
  const { TRAINING_PLAN } = await vite.ssrLoadModule("/components/narma/narma-analysis.tsx");
  const coachingCopy = JSON.stringify({
    stages: data.STAGES,
    axes: data.AXIS_COPY,
    plan: TRAINING_PLAN,
  });

  for (const unsupported of ["Black Hole", "BKB", "Blink", "Requiem", "Eclipse"]) {
    assert.equal(coachingCopy.includes(unsupported), false, `unsupported replay claim: ${unsupported}`);
  }
});

test("public demo render contains no former player identities or match identifier", async () => {
  const React = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { default: NarmaAnalysis } = await vite.ssrLoadModule("/components/narma/narma-analysis.tsx");
  const html = renderToStaticMarkup(React.createElement(NarmaAnalysis, {
    viewer: null, signInHref: "/signin", signOutHref: "/signout",
  }));
  assert.match(html, /Учебный сценарий/);
  assert.match(html, /Все игроки, показатели и события вымышлены/);
  assert.doesNotMatch(html, /8963624400|papa_prima/i);
});
