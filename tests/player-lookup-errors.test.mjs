import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createServer } from "vite";
import { analysisRoot, makeOpenDotaMatch, jsonResponse } from "./analysis-test-helpers.mjs";
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
const { fetchOpenDotaMatch, fetchOpenDotaRoster } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");
const { accountApiError } = await vite.ssrLoadModule("/lib/auth/api-account.ts");
const { analysisErrorResponse, handleCreateAnalysis } = await vite.ssrLoadModule("/lib/analyses/http.ts");
const { scanUnavailable } = await vite.ssrLoadModule("/lib/scan/errors.ts");
const matchId = "8963624400";
function roster() {
  return { match_id: Number(matchId), version: null,
    players: makeOpenDotaMatch().players.map((p, i) => ({
      player_slot: p.player_slot, hero_id: p.hero_id,
      account_id: 1000 + i, personaname: `Player_${i}`,
    })),
  };
}
async function setup() {
  const db = await database();
  db.sqlite.prepare("INSERT INTO users(id,display_name) VALUES ('owner','Test')").run();
  return { ...db, store: new D1PlayerBindingStore(db.d1) };
}
function assertUnbound(sqlite) {
  for (const table of ["dota_player_profiles", "dota_match_targets", "analysis_jobs", "entitlement_ledger"])
    assert.equal(sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 0);
}

test("basic unparsed roster binds without combat statistics or an analytics cache", async () => {
  const { sqlite, store } = await setup();
  try {
    const raw = roster();
    raw.teamfights = "unavailable"; // Irrelevant to a player's identity.
    raw.players.reverse(); // Use explicit slots, never row offsets.
    const target = await store.resolve("owner", { matchId, nickname: "player_0" }, { fetch: async () => jsonResponse(raw) });
    assert.equal(target.accountId, 1000);
    assert.equal(target.playerSlot, 0);
    assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM source_matches").get().n, 0);
    await assert.rejects(fetchOpenDotaMatch(matchId, { fetch: async () => jsonResponse(makeOpenDotaMatch({ version: null })) }),
      error => error.code === "OPENDOTA_MATCH_NOT_PARSED");
  } finally { sqlite.close(); }
});

test("wrong match, incomplete roster and duplicate slots never bind an account", async () => {
  for (const mutate of [raw => { raw.match_id++; }, raw => { raw.players.pop(); }, raw => { raw.players[1].player_slot = 0; }]) {
    const { sqlite, store } = await setup();
    try {
      const raw = roster(); mutate(raw);
      await assert.rejects(store.resolve("owner", { matchId, nickname: "Player_0" }, { fetch: async () => jsonResponse(raw) }),
        error => error.code === "OPENDOTA_INVALID_RESPONSE");
      assertUnbound(sqlite);
    } finally { sqlite.close(); }
  }
});

test("provider failures keep their safe codes and retry headers at both API boundaries", async () => {
  for (const [status, code, expectedStatus] of [[404, "OPENDOTA_MATCH_NOT_FOUND", 404], [429, "OPENDOTA_RATE_LIMITED", 503], [503, "OPENDOTA_UNAVAILABLE", 503], [403, "OPENDOTA_INVALID_RESPONSE", 503]]) {
    const { sqlite, store } = await setup();
    try {
      let failure;
      try {
        await store.resolve("owner", { matchId, nickname: "Player_0" }, { fetch: async () => new Response("SECRET PROVIDER BODY", { status, headers: { "Retry-After": "17" } }) });
      } catch (error) { failure = error; }
      assert.equal(failure.code, code);
      for (const boundary of [accountApiError, analysisErrorResponse]) {
        const response = boundary(failure);
        assert.equal(response.status, expectedStatus);
        assert.equal(response.headers.get("Cache-Control"), "no-store");
        assert.equal(response.headers.get("Retry-After"), status === 429 ? "17" : null);
        const body = await response.json();
        assert.equal(body.code ?? body.error.code, code);
        assert.doesNotMatch(JSON.stringify(body), /SECRET PROVIDER BODY|Не удалось сохранить изменения/);
      }
      assertUnbound(sqlite);
    } finally { sqlite.close(); }
  }
});

test("roster timeouts and connection failures retain dependency errors", async () => {
  const failed = fetchOpenDotaRoster(matchId, { fetch: async () => { throw new Error("SECRET CONNECTION"); } });
  await assert.rejects(failed, error => error.code === "OPENDOTA_UNAVAILABLE");
  await assert.rejects(fetchOpenDotaRoster(matchId, { timeoutMs: 5, fetch: async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
  }) }), error => error.code === "OPENDOTA_UNAVAILABLE");
});

test("analysis creation preserves lookup failure before reserving a credit; unexpected details stay private", async () => {
  let failure;
  try { await fetchOpenDotaRoster(matchId, { fetch: async () => new Response(null, { status: 404 }) }); }
  catch (error) { failure = error; }
  let reservations = 0;
  const response = await handleCreateAnalysis(new Request("https://narma.test/api/analyses", {
    method: "POST", headers: { Origin: "https://narma.test", "Content-Type": "application/json", "Idempotency-Key": "lookup:failure" },
    body: JSON.stringify({ matchId, nickname: "Player_0" }),
  }), { account: { id: "owner", status: "active", deletedAt: null }, acceptingJobs: true,
    resolveTarget: async () => { throw failure; }, store: { create: async () => { reservations++; } },
  });
  assert.equal(response.status, 404);
  assert.equal((await response.json()).error.code, "OPENDOTA_MATCH_NOT_FOUND");
  assert.equal(reservations, 0);
  for (const boundary of [accountApiError, analysisErrorResponse]) {
    const storage = await boundary(scanUnavailable()).json();
    assert.equal(storage.code ?? storage.error.code, "SCAN_UNAVAILABLE");
    assert.doesNotMatch(await boundary(new Error("SECRET DB DETAILS")).text(), /SECRET DB DETAILS/);
  }
});
