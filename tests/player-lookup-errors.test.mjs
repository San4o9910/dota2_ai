import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createServer } from "vite";
import { analysisRoot } from "./analysis-test-helpers.mjs";
import { database } from "./sqlite-d1.mjs";

const vite = await createServer({
  appType: "custom", configFile: false, root: analysisRoot,
  resolve: { alias: { "@": analysisRoot } }, server: { middlewareMode: true },
  plugins: [{ name: "lookup-test-env", enforce: "pre",
    resolveId(source) { if (source === "cloudflare:workers") return "\0lookup-env"; },
    load(id) { if (id === "\0lookup-env") return "export const env = {};"; },
  }],
});
after(() => vite.close());
const { D1PlayerBindingStore } = await vite.ssrLoadModule("/lib/dota/player-binding.ts");
const { fetchOpenDotaRoster } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");
const { accountApiError } = await vite.ssrLoadModule("/lib/auth/api-account.ts");
const { analysisErrorResponse, handleCreateAnalysis } = await vite.ssrLoadModule("/lib/analyses/http.ts");
const { scanUnavailable } = await vite.ssrLoadModule("/lib/scan/errors.ts");
const matchId = "8963624400";
async function setup() {
  const db = await database();
  db.sqlite.prepare("INSERT INTO users(id,display_name) VALUES ('owner','Test')").run();
  return { ...db, store: new D1PlayerBindingStore(db.d1) };
}
function assertUnbound(sqlite) {
  for (const table of ["dota_player_profiles", "dota_match_targets", "analysis_jobs", "entitlement_ledger"])
    assert.equal(sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0);
}

test("a match ID alone never performs remote identity lookup or reserves analysis credit", async () => {
  const { sqlite, store } = await setup();
  let calls = 0;
  try {
    await assert.rejects(store.resolve("owner", { matchId, nickname: "Player_0" }, { fetch: async () => { calls++; throw Error("network"); } }),
      error => error.code === "DOTA_REPLAY_REQUIRED" && !error.retryable);
    assert.equal(calls, 0);
    assertUnbound(sqlite);
  } finally { sqlite.close(); }
});

test("retirement is a permanent safe 410 at both API error boundaries", async () => {
  let failure;
  try { await fetchOpenDotaRoster(matchId, { fetch: async () => assert.fail("network") }); }
  catch (error) { failure = error; }
  for (const boundary of [accountApiError, analysisErrorResponse]) {
    const response = boundary(failure);
    assert.equal(response.status, 410);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.equal(response.headers.get("Retry-After"), null);
    const body = await response.json();
    assert.equal(body.code ?? body.error.code, "SOURCE_RETIRED");
    assert.doesNotMatch(JSON.stringify(body), /SECRET|OpenDota/);
  }
});

test("analysis creation preserves retirement before reserving a credit; unexpected details stay private", async () => {
  let failure;
  try { await fetchOpenDotaRoster(matchId); } catch (error) { failure = error; }
  let reservations = 0;
  const response = await handleCreateAnalysis(new Request("https://narma.test/api/analyses", {
    method: "POST", headers: { Origin: "https://narma.test", "Content-Type": "application/json", "Idempotency-Key": "lookup:failure" },
    body: JSON.stringify({ matchId, nickname: "Player_0" }),
  }), { account: { id: "owner", status: "active", deletedAt: null }, acceptingJobs: true,
    resolveTarget: async () => { throw failure; }, store: { create: async () => { reservations++; } },
  });
  assert.equal(response.status, 410);
  assert.equal((await response.json()).error.code, "SOURCE_RETIRED");
  assert.equal(reservations, 0);
  for (const boundary of [accountApiError, analysisErrorResponse]) {
    const storage = await boundary(scanUnavailable()).json();
    assert.equal(storage.code ?? storage.error.code, "SCAN_UNAVAILABLE");
    assert.doesNotMatch(await boundary(new Error("SECRET DB DETAILS")).text(), /SECRET DB DETAILS/);
  }
});
