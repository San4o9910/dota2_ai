import assert from "node:assert/strict";
import test, { after } from "node:test";

import {
  createAnalysisVite,
  jsonResponse,
  makeOpenDotaMatch,
  makeReport,
  openAIResponse,
} from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { ANALYSIS_PROMPT_VERSION, runOwnedAnalysis } = await vite.ssrLoadModule("/lib/analyses/service.ts");

const claim = {
  id: "123e4567-e89b-42d3-a456-426614174000",
  userId: "user-analysis",
  matchId: "8963624400",
  playerSlot: 0,
  reportVersion: "analysis-report.v1",
  attempt: 1,
  maxAttempts: 3,
  reservationId: "123e4567-e89b-42d3-a456-426614174001",
  leaseToken: "123e4567-e89b-42d3-a456-426614174002",
};

function dependencies(overrides = {}) {
  const events = [];
  let cached = null;
  return {
    events,
    dependencies: {
      store: {
        claimOwned: async () => ({ outcome: "claimed", claim }),
        complete: async (_claim, input) => {
          events.push({ type: "complete", input });
          return true;
        },
        fail: async (_claim, failure) => {
          events.push({ type: "fail", failure });
          return failure.retryable
            ? { outcome: "queued", retryAfterSeconds: failure.retryAfterSeconds ?? 5 }
            : { outcome: "failed" };
        },
        getOwned: async () => null,
      },
      cache: {
        get: async () => cached,
        put: async (match) => {
          cached = match;
          events.push({ type: "cache", match });
        },
      },
      apiKey: "server-secret-key-with-enough-length",
      model: "model-approved",
      allowedModels: ["model-approved"],
      authorizeTarget:async (_user,matchId,playerSlot)=>({matchId,playerSlot,accountId:1000,heroId:1,nickname:"Test player"}),
      fetch: async (input, init) => {
        const url = String(input);
        if (url.includes("api.opendota.com")) return jsonResponse(makeOpenDotaMatch());
        if (url.includes("api.openai.com")) {
          const body = JSON.parse(init.body);
          const userInput = JSON.parse(body.input[1].content);
          events.push({ type: "openai", body });
          return jsonResponse(openAIResponse(makeReport(userInput.evidenceHash)));
        }
        throw new Error(`Unexpected URL: ${url}`);
      },
      ...overrides,
    },
  };
}

test("leased runner normalizes, validates and completes one report", async () => {
  const fixture = dependencies();
  const result = await runOwnedAnalysis(
    "user-analysis",
    claim.id,
    fixture.dependencies,
  );
  assert.equal(result.outcome, "completed");
  assert.deepEqual(fixture.events.map((event) => event.type), ["cache", "openai", "complete"]);
  const completed = fixture.events.find((event) => event.type === "complete").input;
  assert.equal(completed.report.matchId, claim.matchId);
  assert.equal(completed.report.playerSlot, claim.playerSlot);
  assert.equal(completed.evidenceBundle.matchId, claim.matchId);
  assert.equal(completed.model, "model-approved");
  assert.equal(completed.promptVersion, ANALYSIS_PROMPT_VERSION);
  assert.equal(completed.promptVersion, "narma-coach.v3-grounded-selection");
});

test("retryable provider failure returns the durable job to queued", async () => {
  const fixture = dependencies({
    fetch: async (input) => String(input).includes("api.opendota.com")
      ? jsonResponse(makeOpenDotaMatch())
      : new Response(null, { status: 503 }),
  });
  const result = await runOwnedAnalysis(
    "user-analysis",
    claim.id,
    fixture.dependencies,
  );
  assert.equal(result.outcome, "retry_queued");
  const failure = fixture.events.find((event) => event.type === "fail").failure;
  assert.equal(failure.code, "OPENAI_UNAVAILABLE");
  assert.equal(failure.retryable, true);
  assert.equal(result.retryAfterSeconds, 5);
});

test("provider Retry-After survives failure persistence and the run response", async () => {
  const fixture = dependencies({
    fetch: async (input) => String(input).includes("api.opendota.com")
      ? jsonResponse(makeOpenDotaMatch())
      : new Response(null, { status: 429, headers: { "Retry-After": "23" } }),
  });
  const result = await runOwnedAnalysis("user-analysis", claim.id, fixture.dependencies);
  assert.equal(result.outcome, "retry_queued");
  assert.equal(result.retryAfterSeconds, 23);
  const failure = fixture.events.find((event) => event.type === "fail").failure;
  assert.equal(failure.retryAfterSeconds, 23);
});

test("busy or foreign jobs never call providers", async () => {
  let providerCalls = 0;
  const fixture = dependencies({
    store: {
      claimOwned: async () => ({ outcome: "not_found" }),
      getOwned: async () => null,
    },
    fetch: async () => {
      providerCalls += 1;
      throw new Error("must not run");
    },
  });
  const result = await runOwnedAnalysis("foreign-user", claim.id, fixture.dependencies);
  assert.equal(result.outcome, "not_found");
  assert.equal(providerCalls, 0);
});

test("busy lease returns its recovery delay without calling providers", async () => {
  let providerCalls = 0;
  const fixture = dependencies({
    store: {
      claimOwned: async () => ({ outcome: "busy", retryAfterSeconds: 42 }),
      getOwned: async () => null,
    },
    fetch: async () => {
      providerCalls += 1;
      throw new Error("must not run");
    },
  });
  const result = await runOwnedAnalysis("user-analysis", claim.id, fixture.dependencies);
  assert.equal(result.outcome, "busy");
  assert.equal(result.retryAfterSeconds, 42);
  assert.equal(providerCalls, 0);
});
