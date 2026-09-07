import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createAnalysisVite, expectAnalysisCode, makeOpenDotaMatch } from "./analysis-test-helpers.mjs";
const vite = await createAnalysisVite();
after(() => vite.close());
const { fetchOpenDotaMatch, fetchOpenDotaRoster, OpenDotaMatchSchema } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");

test("retired remote source cannot call global or explicitly supplied fetch", async () => {
  let calls = 0;
  const original = globalThis.fetch;
  const forbiddenFetch = async () => { calls++; throw new Error("network must not run"); };
  globalThis.fetch = forbiddenFetch;
  try {
    for (const load of [fetchOpenDotaMatch, fetchOpenDotaRoster]) {
      for (const options of [undefined, { fetch: forbiddenFetch }, { fetch: forbiddenFetch, signal: AbortSignal.abort(), timeoutMs: 1 }]) {
        await expectAnalysisCode(assert, load("8963624400", options), "SOURCE_RETIRED", { httpStatus: 410, retryable: false });
      }
    }
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test("retired source still rejects malformed IDs without touching transport", async () => {
  for (const load of [fetchOpenDotaMatch, fetchOpenDotaRoster]) {
    for (const id of ["1234567", "0123456789", "1234567890123", "8963624400/parse", "https://attacker.test/12345678", "8963624400?x=1", "8.9636244e9", "１２３４５６７８"]) {
      await expectAnalysisCode(assert, load(id, { fetch: async () => assert.fail("network call") }), "INVALID_MATCH_ID", { httpStatus: 400, retryable: false });
    }
  }
});

test("archived payloads retain truthful schema validation without remote transport", () => {
  assert.equal(OpenDotaMatchSchema.parse(makeOpenDotaMatch()).version, 21);
  assert.equal(OpenDotaMatchSchema.safeParse(makeOpenDotaMatch({ players: [] })).success, false);
});
