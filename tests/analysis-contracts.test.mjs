import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test, { after } from "node:test";

import { createAnalysisVite, makeOpenDotaMatch, makeReport } from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const contracts = await vite.ssrLoadModule("/lib/analysis/contracts.ts");
const canonical = await vite.ssrLoadModule("/lib/analysis/canonical-json.ts");
const errors = await vite.ssrLoadModule("/lib/analysis/errors.ts");
const http = await vite.ssrLoadModule("/lib/analysis/http.ts");
const { OpenDotaMatchSchema } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");
const { normalizeOpenDotaMatch, buildEvidenceBundle } = await vite.ssrLoadModule("/lib/analysis/normalizer.ts");

test("canonical JSON and SHA-256 are stable across object insertion order", async () => {
  const left = { z: 1, nested: { b: true, a: [3, null, "x"] }, a: -0 };
  const right = { a: 0, nested: { a: [3, null, "x"], b: true }, z: 1 };
  const expected = '{"a":0,"nested":{"a":[3,null,"x"],"b":true},"z":1}';

  assert.equal(canonical.canonicalJson(left), expected);
  assert.equal(canonical.canonicalJson(right), expected);
  assert.equal(
    await canonical.canonicalSha256(left),
    createHash("sha256").update(expected).digest("hex"),
  );
  assert.throws(() => canonical.canonicalJson({ invalid: Number.NaN }), /finite numbers/);
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => canonical.canonicalJson(cyclic), /cycles/);
});

test("versioned contracts reject unknown fields and invalid cross-field facts", async () => {
  const raw = OpenDotaMatchSchema.parse(makeOpenDotaMatch());
  const normalized = normalizeOpenDotaMatch(raw);
  const artifacts = await buildEvidenceBundle(normalized);

  assert.equal(contracts.NormalizedMatchV1Schema.parse(normalized).schemaVersion, "normalized-match.v1");
  assert.equal(contracts.EvidenceBundleV1Schema.parse(artifacts.evidenceBundle).schemaVersion, "evidence-bundle.v1");
  assert.equal(contracts.NormalizedMatchV1Schema.safeParse({ ...normalized, chat: [] }).success, false);
  assert.equal(contracts.EvidenceBundleV1Schema.safeParse({ ...artifacts.evidenceBundle, accountId: 1 }).success, false);
  assert.equal(contracts.NormalizedMatchV1Schema.safeParse({
    ...normalized,
    players: normalized.players.map((player, index) => index === 0 ? { ...player, isRadiant: false } : player),
  }).success, false);
  assert.equal(contracts.EvidenceBundleV1Schema.safeParse({
    ...artifacts.evidenceBundle,
    evidence: [...artifacts.evidenceBundle.evidence, artifacts.evidenceBundle.evidence[0]],
  }).success, false);
});

test("report contract requires structured numeric claims and has a strict Responses JSON schema", async () => {
  const raw = OpenDotaMatchSchema.parse(makeOpenDotaMatch());
  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(raw));
  const report = makeReport(artifacts.evidenceHash);

  assert.equal(contracts.AnalysisReportV1Schema.parse(report).schemaVersion, "analysis-report.v1");
  assert.equal(contracts.AnalysisReportV1Schema.safeParse({
    ...report,
    items: [{ ...report.items[0], kind: "fact" }],
  }).success, false);
  assert.equal(contracts.AnalysisReportV1Schema.safeParse({
    ...report,
    items: [{ ...report.items[0], secret: "unexpected" }],
  }).success, false);
  const itemWithoutClaims = structuredClone(report.items[0]);
  delete itemWithoutClaims.claims;
  assert.equal(contracts.AnalysisReportV1Schema.safeParse({
    ...report,
    items: [itemWithoutClaims],
  }).success, false);

  const schema = contracts.ANALYSIS_REPORT_V1_JSON_SCHEMA;
  assert.equal(schema.additionalProperties, false);
  assert.deepEqual(schema.required, ["schemaVersion", "matchId", "playerSlot", "evidenceHash", "items", "limitations"]);
  assert.equal(schema.properties.items.items.additionalProperties, false);
  assert.ok(schema.properties.items.items.required.includes("evidenceIds"));
  assert.ok(schema.properties.items.items.required.includes("claims"));
  assert.equal(schema.properties.items.items.properties.claims.minItems, 1);
  assert.equal(schema.properties.items.items.properties.claims.items.additionalProperties, false);
  assert.deepEqual(
    schema.properties.items.items.properties.claims.items.required,
    ["evidenceId", "metric", "value", "unit"],
  );
  assert.equal(schema.properties.items.items.properties.title.pattern, "^[^0-9]*$");
  assert.equal(schema.properties.items.items.properties.body.pattern, "^[^0-9]*$");
});

test("all report prose rejects unstructured quantitative language", async () => {
  const raw = OpenDotaMatchSchema.parse(makeOpenDotaMatch());
  const artifacts = await buildEvidenceBundle(normalizeOpenDotaMatch(raw));
  const report = makeReport(artifacts.evidenceHash);
  const cases = [
    { ...report, items: [{ ...report.items[0], title: "Разберите 2 ошибки" }] },
    { ...report, items: [{ ...report.items[0], body: "У игрока было ٣ смерти." }] },
    { ...report, items: [{ ...report.items[0], limitations: ["Нет данных за Ⅳ минуту."] }] },
    { ...report, limitations: ["Доступен только １ источник."] },
    { ...report, items: [{ ...report.items[0], title: "Десять ошибок" }] },
    { ...report, items: [{ ...report.items[0], body: "Темп вырос вдвое." }] },
    { ...report, items: [{ ...report.items[0], limitations: ["Доступна половина данных."] }] },
    { ...report, limitations: ["Погрешность один процент."] },
    { ...report, limitations: ["Погрешность выражена в процентах."] },
    { ...report, items: [{ ...report.items[0], body: "Значение равно 1e3." }] },
    { ...report, items: [{ ...report.items[0], body: "Разница равна −2." }] },
    { ...report, items: [{ ...report.items[0], body: "Среднее значение равно 3,14." }] },
  ];
  for (const candidate of cases) {
    assert.equal(contracts.AnalysisReportV1Schema.safeParse(candidate).success, false);
  }

  assert.equal(contracts.AnalysisReportV1Schema.parse(report).items[0].claims[0].value, 1);
});

test("typed public/dependency errors expose only the stable public envelope", () => {
  const error = new errors.AnalysisDependencyError("openai", "OPENAI_UNAVAILABLE", "Временно недоступно.", {
    httpStatus: 503,
    retryable: true,
    cause: new Error("provider secret body"),
  });
  assert.deepEqual(errors.toAnalysisErrorEnvelope(error, "req_123"), {
    error: {
      code: "OPENAI_UNAVAILABLE",
      message: "Временно недоступно.",
      retryable: true,
      requestId: "req_123",
    },
  });
  assert.equal(error.dependency, "openai");
  assert.equal(errors.parseRetryAfterSeconds("12.2"), 13);
  assert.equal(errors.parseRetryAfterSeconds("not-a-date"), undefined);
});

test("timeout and bounded-reader cleanup remove abort listeners", async () => {
  const listeners = new Set();
  const signal = {
    aborted: false,
    reason: undefined,
    addEventListener(type, listener) { if (type === "abort") listeners.add(listener); },
    removeEventListener(type, listener) { if (type === "abort") listeners.delete(listener); },
  };
  const timeout = http.createTimeoutContext(1_000, signal);
  assert.equal(listeners.size, 1);
  timeout.cleanup();
  assert.equal(listeners.size, 0);

  await http.readBoundedJson(new Response("{}", {
    headers: { "content-type": "application/json" },
  }), { dependency: "openai", maxBytes: 10, signal });
  assert.equal(listeners.size, 0);
});
