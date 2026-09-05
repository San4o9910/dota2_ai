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

test("training plan covers every stage and every analysis axis", async () => {
  const { MATCH } = await vite.ssrLoadModule("/app/data/match-8963624400.ts");
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
  const data = await vite.ssrLoadModule("/app/data/match-8963624400.ts");
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
