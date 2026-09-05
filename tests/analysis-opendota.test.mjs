import assert from "node:assert/strict";
import test, { after } from "node:test";

import {
  createAnalysisVite,
  expectAnalysisCode,
  jsonResponse,
  makeOpenDotaMatch,
} from "./analysis-test-helpers.mjs";

const vite = await createAnalysisVite();
after(async () => vite.close());

const { fetchOpenDotaMatch, OPENDOTA_ORIGIN } = await vite.ssrLoadModule("/lib/analysis/opendota.ts");

test("OpenDota fetch is a fixed-origin bounded GET and never issues parse POST", async () => {
  let captured;
  const result = await fetchOpenDotaMatch("8963624400", {
    fetch: async (input, init) => {
      captured = { input, init };
      return jsonResponse(makeOpenDotaMatch());
    },
  });

  const url = new URL(String(captured.input));
  assert.equal(url.origin, OPENDOTA_ORIGIN);
  assert.equal(url.pathname, "/api/matches/8963624400");
  assert.equal(url.search, "");
  assert.equal(captured.init.method, "GET");
  assert.equal(captured.init.redirect, "error");
  assert.equal(captured.init.body, undefined);
  assert.equal(captured.init.headers.accept, "application/json");
  assert.equal(result.version, 21);
});

test("invalid Match IDs are rejected before fetch and cannot alter origin/path", async () => {
  for (const matchId of [
    "1234567",
    "0123456789",
    "1234567890123",
    "8963624400/parse",
    "https://attacker.test/12345678",
    "8963624400?x=1",
    "8.9636244e9",
    "１２３４５６７８",
  ]) {
    let called = false;
    await expectAnalysisCode(assert, fetchOpenDotaMatch(matchId, {
      fetch: async () => {
        called = true;
        throw new Error("must not run");
      },
    }), "INVALID_MATCH_ID", { httpStatus: 400, retryable: false });
    assert.equal(called, false, matchId);
  }
});

test("OpenDota maps 404, 429 and 5xx without exposing provider bodies", async () => {
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response("provider private details", { status: 404 }),
  }), "OPENDOTA_MATCH_NOT_FOUND", { httpStatus: 404, retryable: false });

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response("quota account detail", {
      status: 429,
      headers: { "retry-after": "17" },
    }),
  }), "OPENDOTA_RATE_LIMITED", { httpStatus: 503, retryable: true, retryAfterSeconds: 17 });

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response("upstream trace", { status: 503 }),
  }), "OPENDOTA_UNAVAILABLE", { httpStatus: 503, retryable: true });
});

test("non-OK OpenDota response bodies are cancelled rather than consumed", async () => {
  let cancelled = false;
  const response = new Response(new ReadableStream({
    pull() {},
    cancel() { cancelled = true; },
  }), { status: 500 });

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => response,
  }), "OPENDOTA_UNAVAILABLE");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(cancelled, true);
});

test("OpenDota rejects wrong content type, malformed JSON and oversized bodies", async () => {
  let wrongTypeCancelled = false;
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode("<html>not json</html>")); },
      cancel() { wrongTypeCancelled = true; },
    }), {
      headers: { "content-type": "text/html" },
    }),
  }), "OPENDOTA_INVALID_RESPONSE");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(wrongTypeCancelled, true);

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response(null, { headers: { "content-type": "application/json" } }),
  }), "OPENDOTA_INVALID_RESPONSE");

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => new Response("{broken", {
      headers: { "content-type": "application/json" },
    }),
  }), "OPENDOTA_INVALID_RESPONSE");

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    maxResponseBytes: 20,
    fetch: async () => new Response("{}", {
      headers: { "content-type": "application/json", "content-length": "21" },
    }),
  }), "UPSTREAM_PAYLOAD_TOO_LARGE", { httpStatus: 413 });

  const encoder = new TextEncoder();
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    maxResponseBytes: 20,
    fetch: async () => new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('{"padding":"'));
        controller.enqueue(encoder.encode("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"));
        controller.close();
      },
    }), { headers: { "content-type": "application/json" } }),
  }), "UPSTREAM_PAYLOAD_TOO_LARGE", { httpStatus: 413 });
});

test("OpenDota fails closed on unparsed, mismatched and malformed match payloads", async () => {
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => jsonResponse(makeOpenDotaMatch({ version: null })),
  }), "OPENDOTA_MATCH_NOT_PARSED", { retryable: false });

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => jsonResponse(makeOpenDotaMatch({ match_id: 8963624401 })),
  }), "OPENDOTA_INVALID_RESPONSE");

  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    fetch: async () => jsonResponse(makeOpenDotaMatch({ players: makeOpenDotaMatch().players.slice(0, 9) })),
  }), "OPENDOTA_INVALID_RESPONSE");
});

test("OpenDota timeout covers fetch and a body that stalls after headers", async () => {
  const fetchStarted = Date.now();
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    timeoutMs: 30,
    fetch: async (_input, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    }),
  }), "OPENDOTA_UNAVAILABLE", { retryable: true });
  assert.ok(Date.now() - fetchStarted < 1_000);

  let bodyCancelled = false;
  const bodyStarted = Date.now();
  await expectAnalysisCode(assert, fetchOpenDotaMatch("8963624400", {
    timeoutMs: 30,
    fetch: async () => new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("{"));
      },
      cancel() { bodyCancelled = true; },
    }), { headers: { "content-type": "application/json" } }),
  }), "OPENDOTA_UNAVAILABLE", { retryable: true });
  assert.ok(Date.now() - bodyStarted < 1_000);
  assert.equal(bodyCancelled, true);
});

test("caller abort is typed as analysis cancellation rather than provider failure", async () => {
  const controller = new AbortController();
  const pending = fetchOpenDotaMatch("8963624400", {
    signal: controller.signal,
    timeoutMs: 1_000,
    fetch: async (_input, init) => new Promise((_resolve, reject) => {
      if (init.signal.aborted) {
        reject(init.signal.reason);
        return;
      }
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    }),
  });
  controller.abort(new DOMException("caller stopped", "AbortError"));
  await expectAnalysisCode(assert, pending, "ANALYSIS_CANCELLED", { httpStatus: 503, retryable: true });
});
