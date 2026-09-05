import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test, { after } from "node:test";
import { DatabaseSync } from "node:sqlite";

import {
  createAnalysisVite,
  jsonResponse,
  makeOpenDotaMatch,
} from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { handleScanPost, scanDisabledResponse, MAX_SCAN_REQUEST_BYTES } = await vite.ssrLoadModule(
  "/lib/scan/handler.ts",
);
const { parseScanRuntime } = await vite.ssrLoadModule("/lib/scan/runtime-config.ts");
const { normalizeConnectingIp, hashRateLimitIdentity } = await vite.ssrLoadModule("/lib/scan/privacy.ts");
const {
  D1FixedWindowRateLimiter,
  D1ScanMatchCache,
  SCAN_NORMALIZER_VERSION,
} = await vite.ssrLoadModule("/lib/scan/storage.ts");
const { normalizeOpenDotaMatch } = await vite.ssrLoadModule("/lib/analysis/normalizer.ts");
const { OpenDotaMatchSchema } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");
const { canonicalJson, canonicalSha256 } = await vite.ssrLoadModule("/lib/analysis/canonical-json.ts");
const { BoundedJsonError, readBoundedJson } = await vite.ssrLoadModule("/lib/security/bounded-json.ts");

const MATCH_ID = "8963624400";
const REQUEST_ID = "00000000-0000-4000-8000-000000000001";
const RATE_SECRET = "s".repeat(32);

function request(body, headers = {}) {
  return new Request("https://narma.test/api/scan", {
    method: "POST",
    headers: {
      Origin: "https://narma.test",
      "CF-Connecting-IP": "203.0.113.7",
      "Content-Type": "application/json",
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function memoryCache(initial = null) {
  let value = initial;
  const puts = [];
  return {
    get puts() { return puts; },
    async get(matchId) {
      return value?.matchId === matchId ? structuredClone(value) : null;
    },
    async put(match) {
      value = structuredClone(match);
      puts.push(structuredClone(match));
    },
  };
}

function allowRateLimiter(overrides = {}) {
  const keys = [];
  return {
    keys,
    async take(keyHash) {
      keys.push(keyHash);
      return {
        allowed: true,
        count: 1,
        limit: 12,
        retryAfterSeconds: 900,
        ...overrides,
      };
    },
  };
}

function handlerDependencies(overrides = {}) {
  return {
    cache: memoryCache(),
    rateLimiter: allowRateLimiter(),
    rateLimitSecret: RATE_SECRET,
    requestId: () => REQUEST_ID,
    fetch: async () => jsonResponse(makeOpenDotaMatch()),
    now: () => 1_750_000_000_000,
    ...overrides,
  };
}

async function bodyOf(response) {
  assert.equal(response.headers.get("cache-control"), "no-store");
  return response.json();
}

function sqliteAsD1(database) {
  return {
    prepare(sql) {
      const statement = database.prepare(sql);
      let values = [];
      const execute = (method) => {
        const numberedParameters = [...sql.matchAll(/\?(\d+)/g)];
        if (numberedParameters.length === 0) return statement[method](...values);
        const parameters = {};
        for (const [, index] of numberedParameters) {
          parameters[index] = values[Number(index) - 1];
        }
        return statement[method](parameters);
      };
      return {
        bind(...bound) { values = bound; return this; },
        async first() {
          const row = execute("get");
          return row ? { ...row } : null;
        },
        async run() {
          execute("run");
          return { success: true };
        },
      };
    },
  };
}

test("Scan runtime is ready only with exact flag, >=32-char secret, and D1 binding", () => {
  const db = { prepare() {} };
  assert.equal(parseScanRuntime({}).ready, false);
  assert.equal(parseScanRuntime({
    SCAN_RUNTIME_ENABLED: "TRUE",
    SCAN_RATE_LIMIT_SECRET: RATE_SECRET,
    DB: db,
  }).ready, false);
  assert.equal(parseScanRuntime({
    SCAN_RUNTIME_ENABLED: "true",
    SCAN_RATE_LIMIT_SECRET: "x".repeat(31),
    DB: db,
  }).ready, false);
  assert.equal(parseScanRuntime({
    SCAN_RUNTIME_ENABLED: "true",
    SCAN_RATE_LIMIT_SECRET: RATE_SECRET,
  }).ready, false);
  assert.equal(parseScanRuntime({
    SCAN_RUNTIME_ENABLED: "true",
    SCAN_RATE_LIMIT_SECRET: RATE_SECRET,
    DB: db,
  }).ready, true);
});

test("disabled response uses the uniform safe envelope", async () => {
  const response = scanDisabledResponse(request({ matchId: MATCH_ID }), REQUEST_ID);
  assert.equal(response.status, 503);
  assert.deepEqual(await bodyOf(response), {
    error: {
      code: "SCAN_UNAVAILABLE",
      message: "NARMA Scan временно недоступен. Попробуйте позже.",
      retryable: true,
      requestId: REQUEST_ID,
    },
  });
});

test("Scan rejects cross-origin requests before storage or provider work", async () => {
  let touched = false;
  const response = await handleScanPost(request({ matchId: MATCH_ID }, {
    Origin: "https://attacker.test",
  }), handlerDependencies({
    cache: { async get() { touched = true; }, async put() { touched = true; } },
  }));
  assert.equal(response.status, 403);
  assert.equal((await bodyOf(response)).error.code, "SAME_ORIGIN_REQUIRED");
  assert.equal(touched, false);
});

test("Scan requires exact application/json and bounded strict JSON", async () => {
  for (const contentType of ["application/jsonp", "text/application/json", "application/problem+json"]) {
    const response = await handleScanPost(request({ matchId: MATCH_ID }, {
      "Content-Type": contentType,
    }), handlerDependencies());
    assert.equal(response.status, 415);
    assert.equal((await bodyOf(response)).error.code, "INVALID_CONTENT_TYPE");
  }

  const malformed = await handleScanPost(request("{"), handlerDependencies());
  assert.equal(malformed.status, 400);
  assert.equal((await bodyOf(malformed)).error.code, "INVALID_REQUEST_BODY");

  const unknownField = await handleScanPost(request({ matchId: MATCH_ID, accountId: 42 }), handlerDependencies());
  assert.equal(unknownField.status, 400);
  assert.equal((await bodyOf(unknownField)).error.code, "INVALID_REQUEST_BODY");

  const oversized = await handleScanPost(request(JSON.stringify({
    matchId: MATCH_ID,
    padding: "x".repeat(MAX_SCAN_REQUEST_BYTES),
  })), handlerDependencies());
  assert.equal(oversized.status, 413);
  assert.equal((await bodyOf(oversized)).error.code, "REQUEST_TOO_LARGE");
});

test("shared bounded JSON reader rejects JSONP-like media types", async () => {
  for (const contentType of ["application/jsonp", "text/application/json", "text/plain+json"]) {
    await assert.rejects(
      readBoundedJson(request({ matchId: MATCH_ID }, {
        "Content-Type": contentType,
      }), MAX_SCAN_REQUEST_BYTES),
      (error) => error instanceof BoundedJsonError && error.code === "content_type",
    );
  }
  assert.deepEqual(await readBoundedJson(request({ matchId: MATCH_ID }, {
    "Content-Type": "application/problem+json; charset=utf-8",
  }), MAX_SCAN_REQUEST_BYTES), { matchId: MATCH_ID });
});

test("connecting identity comes only from CF-Connecting-IP and is HMACed", async () => {
  assert.equal(normalizeConnectingIp("203.0.113.007"), "203.0.113.7");
  assert.equal(normalizeConnectingIp("2001:DB8::1"), "2001:db8::1");
  assert.equal(normalizeConnectingIp("not-an-ip"), null);

  const rateLimiter = allowRateLimiter();
  const response = await handleScanPost(request({ matchId: MATCH_ID }, {
    "X-Forwarded-For": "198.51.100.99",
  }), handlerDependencies({ rateLimiter }));
  assert.equal(response.status, 200);
  assert.equal(rateLimiter.keys.length, 1);
  assert.match(rateLimiter.keys[0], /^[a-f0-9]{64}$/);
  assert.equal(rateLimiter.keys[0].includes("203.0.113.7"), false);
  assert.equal(rateLimiter.keys[0].includes("198.51.100.99"), false);
  assert.equal(rateLimiter.keys[0], await hashRateLimitIdentity(RATE_SECRET, "203.0.113.7", 1_749_999_600));
  assert.notEqual(
    rateLimiter.keys[0],
    await hashRateLimitIdentity(RATE_SECRET, "203.0.113.7", 1_750_000_500),
    "the same address must not be linkable across rate windows",
  );
  assert.equal(JSON.stringify(await bodyOf(response)).includes("203.0.113.7"), false);

  const noCloudflareIdentity = await handleScanPost(request({ matchId: MATCH_ID }, {
    "CF-Connecting-IP": "",
    "X-Forwarded-For": "198.51.100.99",
  }), handlerDependencies());
  assert.equal(noCloudflareIdentity.status, 503);
  assert.equal((await bodyOf(noCloudflareIdentity)).error.code, "SCAN_UNAVAILABLE");
});

test("first stage fetches only the fixed OpenDota GET route and returns exactly ten safe players", async () => {
  const upstream = makeOpenDotaMatch();
  upstream.players[0].kills = null;
  let providerRequest;
  const cache = memoryCache();
  const response = await handleScanPost(request({ matchId: MATCH_ID }), handlerDependencies({
    cache,
    fetch: async (input, init) => {
      providerRequest = { url: String(input), init };
      return jsonResponse(upstream);
    },
  }));
  const body = await bodyOf(response);

  assert.equal(response.status, 200);
  assert.equal(providerRequest.url, `https://api.opendota.com/api/matches/${MATCH_ID}`);
  assert.equal(providerRequest.init.method, "GET");
  assert.equal(providerRequest.init.redirect, "error");
  assert.deepEqual(Object.keys(body).sort(), ["match", "players", "status"]);
  assert.deepEqual(body.match, { matchId: MATCH_ID, durationSeconds: 1_800 });
  assert.equal(body.status, "choose_player");
  assert.equal(body.players.length, 10);
  assert.deepEqual(Object.keys(body.players[0]).sort(), [
    "assists", "deaths", "heroId", "kills", "playerSlot", "side",
  ]);
  assert.deepEqual(body.players.map((player) => player.playerSlot), [0, 1, 2, 3, 4, 128, 129, 130, 131, 132]);
  assert.equal(body.players[0].kills, null);
  const serialized = JSON.stringify(body);
  for (const forbidden of ["personaname", "account_id", "SECRET PLAYER", "SECRET CHAT", "chat"]) {
    assert.equal(serialized.includes(forbidden), false, `response leaked ${forbidden}`);
  }
  assert.equal(cache.puts.length, 1);
});

test("second stage returns exactly one existing deterministic ScanPreview", async () => {
  const normalized = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(makeOpenDotaMatch()));
  const cache = memoryCache(normalized);
  let providerCalls = 0;
  const dependencies = handlerDependencies({
    cache,
    fetch: async () => { providerCalls += 1; throw new Error("cache should prevent fetch"); },
  });
  const first = await handleScanPost(request({ matchId: MATCH_ID, playerSlot: 0 }), dependencies);
  const second = await handleScanPost(request({ matchId: MATCH_ID, playerSlot: 0 }), dependencies);
  const left = await bodyOf(first);
  const right = await bodyOf(second);

  assert.equal(first.status, 200);
  assert.deepEqual(right, left);
  assert.deepEqual(Object.keys(left).sort(), ["preview", "status"]);
  assert.equal(left.status, "ready");
  assert.equal(left.preview.schemaVersion, "scan-preview.v1");
  assert.equal(left.preview.matchId, MATCH_ID);
  assert.equal(left.preview.playerSlot, 0);
  assert.equal(left.preview.selectedEvidenceId, "objective.first_blood.0000");
  assert.equal(providerCalls, 0);
});

test("product limit is 429 with Retry-After and no provider call", async () => {
  let providerCalls = 0;
  const response = await handleScanPost(request({ matchId: MATCH_ID }), handlerDependencies({
    rateLimiter: allowRateLimiter({ allowed: false, count: 13, retryAfterSeconds: 321 }),
    fetch: async () => { providerCalls += 1; return jsonResponse(makeOpenDotaMatch()); },
  }));
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "321");
  assert.equal((await bodyOf(response)).error.code, "SCAN_RATE_LIMITED");
  assert.equal(providerCalls, 0);
});

test("storage and rate-limit failures become safe product 503 errors", async () => {
  const sensitive = "D1 INTERNAL secret-table-name";
  const failures = [
    handlerDependencies({
      rateLimiter: { async take() { throw new Error(sensitive); } },
    }),
    handlerDependencies({
      cache: { async get() { throw new Error(sensitive); }, async put() {} },
    }),
    handlerDependencies({
      cache: { async get() { return null; }, async put() { throw new Error(sensitive); } },
    }),
  ];
  for (const dependencies of failures) {
    const response = await handleScanPost(request({ matchId: MATCH_ID }), dependencies);
    const body = await bodyOf(response);
    assert.equal(response.status, 503);
    assert.equal(body.error.code, "SCAN_UNAVAILABLE");
    assert.equal(body.error.requestId, REQUEST_ID);
    assert.equal(JSON.stringify(body).includes(sensitive), false);
  }
});

test("OpenDota 404 remains 404 while provider auth/status failures are safe 503", async () => {
  const missing = await handleScanPost(request({ matchId: MATCH_ID }), handlerDependencies({
    fetch: async () => new Response(null, { status: 404 }),
  }));
  assert.equal(missing.status, 404);
  assert.equal((await bodyOf(missing)).error.code, "OPENDOTA_MATCH_NOT_FOUND");

  for (const status of [401, 402, 429, 500]) {
    const failed = await handleScanPost(request({ matchId: MATCH_ID }), handlerDependencies({
      fetch: async () => new Response("provider secret body", { status }),
    }));
    const body = await bodyOf(failed);
    assert.equal(failed.status, 503, `provider ${status} must be a product 503`);
    assert.equal(["OPENDOTA_INVALID_RESPONSE", "OPENDOTA_RATE_LIMITED", "OPENDOTA_UNAVAILABLE"].includes(body.error.code), true);
    assert.equal(JSON.stringify(body).includes("provider secret body"), false);
    assert.notEqual(body.error.code, "UNAUTHORIZED");
  }
});

test("D1 cache validates schema, match identity and canonical hash", async () => {
  const normalized = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(makeOpenDotaMatch()));
  const normalizedPayload = canonicalJson(normalized);
  const payloadHash = await canonicalSha256(normalized);
  const dbWithRow = (row) => ({
    prepare() {
      return {
        bind() { return this; },
        async first() { return row; },
      };
    },
  });

  assert.deepEqual(await new D1ScanMatchCache(dbWithRow({
    normalizedPayload,
    payloadHash,
  })).get(MATCH_ID), normalized);
  assert.equal(await new D1ScanMatchCache(dbWithRow({
    normalizedPayload,
    payloadHash: "0".repeat(64),
  })).get(MATCH_ID), null);
  assert.equal(await new D1ScanMatchCache(dbWithRow({
    normalizedPayload: normalizedPayload.replace(MATCH_ID, "9963624400"),
    payloadHash,
  })).get(MATCH_ID), null);
  assert.equal(await new D1ScanMatchCache(dbWithRow({
    normalizedPayload: JSON.stringify({ ...normalized, personaname: "SECRET" }),
    payloadHash,
  })).get(MATCH_ID), null);
});

test("D1 cache persists only canonical normalized data, never raw OpenDota identity/chat", async () => {
  const bindings = [];
  const sql = [];
  const db = {
    prepare(statement) {
      sql.push(statement);
      return {
        bind(...values) { bindings.push(values); return this; },
        async run() { return { success: true }; },
      };
    },
  };
  const normalized = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(makeOpenDotaMatch()));
  await new D1ScanMatchCache(db).put(normalized);
  assert.match(sql[0], /INSERT INTO source_matches/);
  assert.equal(bindings[0][2], SCAN_NORMALIZER_VERSION);
  assert.equal(bindings[0][4], canonicalJson(normalized));
  assert.match(bindings[0][5], /^[a-f0-9]{64}$/);
  const serializedBindings = JSON.stringify(bindings);
  for (const forbidden of ["personaname", "account_id", "SECRET PLAYER", "SECRET CHAT", "IGNORE ALL INSTRUCTIONS"]) {
    assert.equal(serializedBindings.includes(forbidden), false, `cache leaked ${forbidden}`);
  }
});

test("D1 fixed-window limiter increments atomically in one upsert statement", async () => {
  let count = 0;
  const statements = [];
  const bindings = [];
  const db = {
    prepare(statement) {
      statements.push(statement);
      return {
        bind(...values) { bindings.push(values); return this; },
        async first() { count += 1; return { count }; },
      };
    },
  };
  const limiter = new D1FixedWindowRateLimiter(db, 2, 900);
  const digest = "a".repeat(64);
  assert.equal((await limiter.take(digest, 1_750_000_000_000)).allowed, true);
  assert.equal((await limiter.take(digest, 1_750_000_001_000)).allowed, true);
  const rejected = await limiter.take(digest, 1_750_000_002_000);
  assert.equal(rejected.allowed, false);
  assert.equal(rejected.count, 3);
  assert.ok(statements.every((statement) => statement.includes("ON CONFLICT(scope, key_hash, window_start) DO UPDATE")));
  assert.ok(statements.every((statement) => statement.includes("RETURNING count")));
  assert.ok(bindings.every((values) => values[1] === "anonymous_scan" && values[2] === digest));
  assert.ok(bindings.every((values) => values[3] === bindings[0][3]));
  assert.equal(JSON.stringify(bindings).includes("203.0.113.7"), false);
});

test("cache and atomic counter SQL execute against the migrated SQLite contract", async () => {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(`
    CREATE TABLE source_matches (
      id TEXT PRIMARY KEY,
      match_id TEXT NOT NULL,
      normalizer_version TEXT NOT NULL,
      source_provider TEXT NOT NULL,
      source_status TEXT NOT NULL,
      parser_version TEXT,
      normalized_payload TEXT,
      payload_hash TEXT,
      fetched_at TEXT,
      normalized_at TEXT,
      last_checked_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(match_id, normalizer_version)
    );
    CREATE TABLE rate_limit_buckets (
      id TEXT PRIMARY KEY,
      scope TEXT NOT NULL,
      key_hash TEXT NOT NULL,
      window_start INTEGER NOT NULL,
      count INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(scope, key_hash, window_start)
    );
  `);
  try {
    const db = sqliteAsD1(sqlite);
    const normalized = normalizeOpenDotaMatch(OpenDotaMatchSchema.parse(makeOpenDotaMatch()));
    const cache = new D1ScanMatchCache(db);
    await cache.put(normalized);
    assert.deepEqual(await cache.get(MATCH_ID), normalized);

    const limiter = new D1FixedWindowRateLimiter(db, 2, 900);
    const digest = "b".repeat(64);
    assert.equal((await limiter.take(digest, 1_750_000_000_000)).count, 1);
    assert.equal((await limiter.take(digest, 1_750_000_001_000)).count, 2);
    const rejected = await limiter.take(digest, 1_750_000_002_000);
    assert.equal(rejected.allowed, false);
    assert.equal(rejected.retryAfterSeconds, 498);
    const nextWindow = await limiter.take(digest, 1_750_000_500_000);
    assert.deepEqual(nextWindow, {
      allowed: true,
      count: 1,
      limit: 2,
      retryAfterSeconds: 900,
    });
    const stored = sqlite.prepare(`
      SELECT window_start, count FROM rate_limit_buckets
      WHERE scope = 'anonymous_scan' ORDER BY window_start
    `).all();
    assert.deepEqual(stored.map((row) => ({ ...row })), [
      { window_start: 1_749_999_600, count: 3 },
      { window_start: 1_750_000_500, count: 1 },
    ]);
  } finally {
    sqlite.close();
  }
});

test("Scan implementation has no OpenAI, entitlement, account, or billing dependency", async () => {
  const files = [
    "app/api/scan/route.ts",
    "lib/scan/handler.ts",
    "lib/scan/service.ts",
    "lib/scan/storage.ts",
  ];
  const source = (await Promise.all(files.map((file) => readFile(new URL(`../${file}`, import.meta.url), "utf8")))).join("\n");
  for (const forbidden of ["lib/analysis/openai", "lib/billing/", "entitlement", "getChatGPTUser", "account_id", "personaname"]) {
    assert.equal(source.includes(forbidden), false, `Scan runtime depends on ${forbidden}`);
  }
});
