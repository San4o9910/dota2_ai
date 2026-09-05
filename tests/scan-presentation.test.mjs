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

const presentation = await vite.ssrLoadModule(
  "/components/narma/scan-presentation.ts",
);

const players = [0, 1, 2, 3, 4, 128, 129, 130, 131, 132].map((playerSlot, index) => ({
  playerSlot,
  heroId: index + 1,
  side: playerSlot < 128 ? "radiant" : "dire",
  kills: index,
  deaths: 2,
  assists: 7,
}));

test("Scan success parser accepts the exact two-stage contract", () => {
  const choose = presentation.parseScanSuccess({
    status: "choose_player",
    match: { matchId: "8963624400", durationSeconds: 2834 },
    players,
  });
  assert.equal(choose?.status, "choose_player");
  assert.equal(choose?.players.length, 10);

  const ready = presentation.parseScanSuccess({
    status: "ready",
    preview: {
      schemaVersion: "scan-preview.v1",
      matchId: "8963624400",
      playerSlot: 0,
      selectedEvidenceId: "fight.0007",
      kind: "fight",
      atSeconds: 461,
      team: "radiant",
      metrics: [{ metric: "radiant_gold_delta", value: -6586, unit: "gold" }],
    },
  });
  assert.equal(ready?.status, "ready");
  assert.equal(ready?.preview.selectedEvidenceId, "fight.0007");
});

test("Scan parser rejects malformed or cross-side roster data", () => {
  assert.equal(presentation.parseScanSuccess({
    status: "choose_player",
    match: { matchId: "8963624400", durationSeconds: 2834 },
    players: players.slice(0, 9),
  }), null);
  assert.equal(presentation.parseScanSuccess({
    status: "choose_player",
    match: { matchId: "8963624400", durationSeconds: 2834 },
    players: players.map((player, index) => index === 0 ? { ...player, side: "dire" } : player),
  }), null);
  assert.equal(presentation.parseScanSuccess({
    status: "ready",
    preview: {
      schemaVersion: "scan-preview.v1",
      matchId: "8963624400",
      playerSlot: 0,
      selectedEvidenceId: "fight.0007",
      kind: "fight",
      atSeconds: 461,
      team: null,
      metrics: [{ metric: "radiant_gold_delta", value: 1.25, unit: "gold" }],
    },
  }), null);
});

test("Scan roster preserves missing K/D/A as unknown, never as zero", () => {
  const parsed = presentation.parseScanSuccess({
    status: "choose_player",
    match: { matchId: "8963624400", durationSeconds: 2834 },
    players: players.map((player, index) => index === 0
      ? { ...player, kills: null, deaths: null, assists: null }
      : player),
  });
  assert.equal(parsed?.status, "choose_player");
  assert.equal(parsed?.players[0].kills, null);
  assert.equal(presentation.formatScanStat(null), "—");
  assert.equal(presentation.formatScanStat(0), "0");
});

test("Scan errors are bounded and preserve retry metadata", () => {
  const parsed = presentation.parseScanError({
    error: {
      code: "RATE_LIMITED",
      message: "Попробуйте позже.",
      retryable: true,
      requestId: "scan_01-test",
    },
  });
  assert.deepEqual(parsed, {
    error: {
      code: "RATE_LIMITED",
      message: "Попробуйте позже.",
      retryable: true,
      requestId: "scan_01-test",
    },
  });
  assert.equal(presentation.parseScanError({
    error: {
      code: "bad-code",
      message: "x",
      retryable: false,
      requestId: "ok",
    },
  }), null);
});

test("Scan labels and metric formatting stay factual and localized", () => {
  assert.equal(presentation.formatScanTime(461), "7:41");
  assert.equal(presentation.formatScanTime(Number.NaN), "0:00");
  assert.equal(presentation.scanKindLabel("fight"), "Командная драка");
  assert.equal(presentation.scanSideLabel(null), "Обе команды");
  assert.equal(presentation.scanMetricLabel("radiant_gold_delta"), "Изменение золота Radiant");
  assert.match(
    presentation.formatScanMetricValue({ metric: "radiant_gold_delta", value: -6586, unit: "gold" }),
    /^[-−]6\s586 золота$/,
  );
  assert.equal(
    presentation.formatScanMetricValue({ metric: "duration", value: 2834, unit: "seconds" }),
    "47:14",
  );
});

test("Scan client accepts JSON media type only, not JSONP lookalikes", () => {
  assert.equal(presentation.isJsonResponseMediaType("application/json"), true);
  assert.equal(presentation.isJsonResponseMediaType("Application/JSON; charset=utf-8"), true);
  assert.equal(presentation.isJsonResponseMediaType("application/jsonp"), false);
  assert.equal(presentation.isJsonResponseMediaType("text/application/json"), false);
  assert.equal(presentation.isJsonResponseMediaType(null), false);
});
