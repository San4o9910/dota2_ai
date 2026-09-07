import assert from "node:assert/strict";
import test, { after } from "node:test";

import { createAnalysisVite } from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { handleCreateAnalysis, MAX_ANALYSIS_REQUEST_BYTES } = await vite.ssrLoadModule(
  "/lib/analyses/http.ts",
);
const { parseAnalysisRuntime } = await vite.ssrLoadModule(
  "/lib/analyses/runtime-config.ts",
);

const account = { id: "user-analysis", status: "active", deletedAt: null };

function request(body, options = {}) {
  return new Request("https://narma.test/api/analyses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Origin: "https://narma.test",
      "Idempotency-Key": "create:analysis:test",
      ...options.headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function dependencies(overrides = {}) {
  return {
    account,
    acceptingJobs: true,
    resolveTarget:async input=>({matchId:input.matchId,playerSlot:0,accountId:1000,heroId:1,nickname:"Test player"}),
    requestId: () => "analysis-request-test",
    store: {
      create: async () => ({
        outcome: "created",
        job: {
          id: "123e4567-e89b-42d3-a456-426614174000",
          matchId: "8963624400",
          playerSlot: 0,
          reportVersion: "analysis-report.v1",
          state: "queued",
          attempt: 0,
          maxAttempts: 3,
          failure: null,
          createdAt: "2026-09-04 00:00:00",
          updatedAt: "2026-09-04 00:00:00",
        },
      }),
    },
    ...overrides,
  };
}

test("analysis runtime requires an operator allowlist before fulfillment", () => {
  const base = {
    ANALYSIS_RUNTIME_ENABLED: "true",
    ANALYSIS_FULFILLMENT_ENABLED: "true",
    OPENAI_API_KEY: "server-secret-key-with-enough-length",
    OPENAI_MODEL: "model-approved",
  };
  assert.deepEqual(parseAnalysisRuntime(base), {
    acceptingJobs: false,
    fulfillmentReady: false,
    apiKey: base.OPENAI_API_KEY,
    model: "model-approved",
    allowedModels: [],
  });
  assert.equal(parseAnalysisRuntime({
    ...base,
    OPENAI_ALLOWED_MODELS: "model-other, model-approved",
  }).fulfillmentReady, true);
  assert.equal(parseAnalysisRuntime({
    ...base,
    ANALYSIS_RUNTIME_ENABLED: "TRUE",
    OPENAI_ALLOWED_MODELS: "model-approved",
  }).acceptingJobs, false);
});

test("create handler validates origin, body and idempotency before reserving", async () => {
  let calls = 0;
  const store = {
    create: async () => {
      calls += 1;
      return dependencies().store.create();
    },
  };
  const invalidOrigin = await handleCreateAnalysis(request(
    { matchId: "8963624400" },
    { headers: { Origin: "https://evil.test" } },
  ), dependencies({ store }));
  assert.equal(invalidOrigin.status, 403);

  const invalidKey = await handleCreateAnalysis(request(
    { matchId: "8963624400" },
    { headers: { "Idempotency-Key": "short" } },
  ), dependencies({ store }));
  assert.equal(invalidKey.status, 400);

  const unknownField = await handleCreateAnalysis(request({
    matchId: "8963624400",
    accountId: "forged",
  }), dependencies({ store }));
  assert.equal(unknownField.status, 400);
  assert.equal(calls, 0);

  const created = await handleCreateAnalysis(request({
    matchId: "8963624400",
  }), dependencies({ store }));
  assert.equal(created.status, 201);
  assert.equal(created.headers.get("location"), "/api/analyses/123e4567-e89b-42d3-a456-426614174000");
  assert.equal(calls, 1);
});

test("create handler returns bounded public errors for disabled, inactive and empty accounts", async () => {
  const disabled = await handleCreateAnalysis(request({
    matchId: "8963624400",
  }), dependencies({ acceptingJobs: false }));
  assert.equal(disabled.status, 503);
  assert.equal((await disabled.json()).error.code, "ANALYSIS_DISABLED");

  const inactive = await handleCreateAnalysis(request({
    matchId: "8963624400",
  }), dependencies({ account: { ...account, status: "deleted", deletedAt: "now" } }));
  assert.equal(inactive.status, 403);

  const empty = await handleCreateAnalysis(request({
    matchId: "8963624400",
  }), dependencies({ store: { create: async () => ({ outcome: "insufficient_entitlement" }) } }));
  assert.equal(empty.status, 402);
  assert.equal((await empty.json()).error.code, "ENTITLEMENT_REQUIRED");

  const oversized = await handleCreateAnalysis(request(JSON.stringify({
    matchId: "8963624400",
    padding: "x".repeat(MAX_ANALYSIS_REQUEST_BYTES),
  })), dependencies());
  assert.equal(oversized.status, 413);
});

