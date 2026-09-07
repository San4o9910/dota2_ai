import assert from "node:assert/strict";
import test, { after } from "node:test";

import { createAnalysisVite, expectAnalysisCode, makeOpenDotaMatch } from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { OpenDotaMatchSchema } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");
const { normalizeOpenDotaMatch, buildEvidenceBundle } = await vite.ssrLoadModule("/lib/analysis/normalizer.ts");
const { buildScanPreview } = await vite.ssrLoadModule("/lib/analysis/scan-preview.ts");

function parsed(overrides = {}) {
  return OpenDotaMatchSchema.parse(makeOpenDotaMatch(overrides));
}

test("normalizer keeps only useful fields, preserves nulls and aggregates deterministically", () => {
  const raw = makeOpenDotaMatch();
  raw.players[0].kills = null;
  const normalized = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(raw));
  const serialized = JSON.stringify(normalized);

  assert.equal(normalized.players.length, 10);
  assert.deepEqual(normalized.players.map((player) => player.playerSlot), [0, 1, 2, 3, 4, 128, 129, 130, 131, 132]);
  assert.equal(normalized.players[0].kills, null);
  assert.equal(normalized.teamTotals.radiant.kills, null, "a partial team total must not be guessed");
  assert.equal(normalized.teamTotals.dire.kills, 35);
  assert.equal(normalized.objectives.length, 2, "unknown/free-text objectives are excluded");
  assert.equal(normalized.objectives[0].id, "objective.first_blood.0000");
  assert.equal(normalized.fights[0].radiant.deaths, 1);
  assert.equal(normalized.fights[0].radiant.kills, 1);
  assert.equal(normalized.economy[3].timeSeconds, 180);
  for (const forbidden of ["personaname", "account_id", "SECRET PLAYER", "SECRET CHAT", "IGNORE ALL INSTRUCTIONS"]) {
    assert.equal(serialized.includes(forbidden), false, `normalization leaked ${forbidden}`);
  }
});

test("rejects reordered players before ordinal teamfight data can mix sides", () => {
  const raw = makeOpenDotaMatch();
  [raw.players[0], raw.players[5]] = [raw.players[5], raw.players[0]];

  const result = OpenDotaMatchSchema.safeParse(raw);
  assert.equal(result.success, false);
  assert.match(
    result.error.issues.map((issue) => issue.message).join("\n"),
    /canonical Dota slot order/,
  );
});

test("normalization and evidence hashes are stable and change with factual data", async () => {
  const first = normalizeOpenDotaMatch(parsed());
  const reordered = makeOpenDotaMatch();
  reordered.objectives.reverse();
  const second = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(reordered));
  assert.deepEqual(second, first);

  const left = await buildEvidenceBundle(first);
  const right = await buildEvidenceBundle(second);
  assert.deepEqual(right, left);
  assert.match(left.normalizedMatchHash, /^[a-f0-9]{64}$/);
  assert.match(left.evidenceHash, /^[a-f0-9]{64}$/);
  assert.equal(new Set(left.evidenceBundle.evidence.map((item) => item.id)).size, left.evidenceBundle.evidence.length);

  const changed = normalizeOpenDotaMatch(parsed({ radiant_score: 33 }));
  const changedArtifacts = await buildEvidenceBundle(changed);
  assert.notEqual(changedArtifacts.normalizedMatchHash, left.normalizedMatchHash);
  assert.notEqual(changedArtifacts.evidenceHash, left.evidenceHash);
});

test("evidence is controlled numeric data and contains no upstream free text or identity", async () => {
  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(parsed()));
  const serialized = JSON.stringify(artifacts.evidenceBundle);

  assert.ok(artifacts.evidenceBundle.evidence.some((item) => item.id === "player.000.summary"));
  assert.ok(artifacts.evidenceBundle.evidence.some((item) => item.id === "fight.0000"));
  for (const item of artifacts.evidenceBundle.evidence) {
    assert.ok(item.values.length >= 1);
    assert.ok(item.values.every((value) => Number.isFinite(value.value)));
  }
  for (const forbidden of ["personaname", "account_id", "SECRET PLAYER", "SECRET CHAT", "IGNORE ALL INSTRUCTIONS"]) {
    assert.equal(serialized.includes(forbidden), false, `evidence leaked ${forbidden}`);
  }
});

test("anonymous Scan selects one deterministic factual moment without model output or PII", async () => {
  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(parsed()));
  const preview = buildScanPreview(artifacts.evidenceBundle, 0);
  const again = buildScanPreview(structuredClone(artifacts.evidenceBundle), 0);

  assert.deepEqual(again, preview);
  assert.equal(preview.schemaVersion, "scan-preview.v1");
  assert.equal(preview.selectedEvidenceId, "objective.first_blood.0000");
  assert.equal(preview.atSeconds, 120);
  assert.equal(Object.hasOwn(preview, "summary"), false);
  assert.equal(Object.hasOwn(preview, "body"), false);
  assert.equal(JSON.stringify(preview).includes("SECRET"), false);

  const otherPlayer = buildScanPreview(artifacts.evidenceBundle, 2);
  assert.equal(otherPlayer.selectedEvidenceId, "fight.0000");
  await expectAnalysisCode(assert, Promise.resolve().then(() => buildScanPreview(artifacts.evidenceBundle, 99)), "INVALID_PLAYER_SLOT", {
    httpStatus: 400,
  });
});

test("Scan has a deterministic match-end fallback when parsed event arrays are empty", async () => {
  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(parsed({
    objectives: [],
    teamfights: [],
    radiant_gold_adv: [],
    radiant_xp_adv: [],
  })));
  const preview = buildScanPreview(artifacts.evidenceBundle, 0);
  assert.equal(preview.selectedEvidenceId, "match.summary");
  assert.equal(preview.atSeconds, 1_800);
  assert.ok(preview.metrics.some((metric) => metric.metric === "duration"));
});
