import assert from "node:assert/strict";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const mocksKey = "__ANALYSIS_RUN_ROUTE_MOCKS__";
const modules = new Map([
  ["next/server", "after"],
  ["@/app/chatgpt-auth", "auth"],
  ["@/lib/analyses/runtime", "runtime"],
  ["@/lib/analyses/service", "service"],
  ["@/lib/analyses/store", "store"],
  ["@/lib/auth/current-account", "account"],
  ["@/lib/scan/storage", "cache"],
  ["@/lib/security/same-origin", "origin"],
]);

const vite = await createServer({
  appType: "custom",
  configFile: false,
  ssr: { noExternal: ["next"] },
  root,
  resolve: { alias: { "@": root } },
  plugins: [{
    name: "analysis-run-route-mocks",
    enforce: "pre",
    resolveId(source) {
      const direct = modules.get(source);
      if (direct) return `\0analysis-run-${direct}`;
      for (const [alias, name] of modules) {
        const absolute = `${root}${alias.slice(1)}`;
        if ([absolute, `${absolute}.ts`].includes(source)) return `\0analysis-run-${name}`;
      }
      return null;
    },
    load(id) {
      if(id === "\0analysis-run-after") return `export function after(promise) { globalThis.${mocksKey}.background = promise; }`;
      if (id === "\0analysis-run-auth") {
        return `export async function getChatGPTUser() { return { id: "chat-user" }; }`;
      }
      if (id === "\0analysis-run-runtime") {
        return `export function getAnalysisRuntime() {
          return {
            fulfillmentReady: true,
            db: {},
            apiKey: "test-key",
            model: "test-model",
            allowedModels: new Set(["test-model"]),
          };
        }`;
      }
      if (id === "\0analysis-run-service") {
        return `export async function runOwnedAnalysis() {
          return globalThis.${mocksKey}.result;
        }`;
      }
      if (id === "\0analysis-run-store") {
        return `export class D1AnalysisStore { constructor() {} }`;
      }
      if (id === "\0analysis-run-account") {
        return `export async function getCurrentAccount() {
          return { id: "account-1", status: "active", deletedAt: null };
        }`;
      }
      if (id === "\0analysis-run-cache") {
        return `export class D1ScanMatchCache { constructor() {} }`;
      }
      if (id === "\0analysis-run-origin") {
        return `export function isSameOriginRequest() { return true; }`;
      }
      return null;
    },
  }],
  server: { middlewareMode: true, hmr: false },
});

after(async () => {
  await vite.close();
  delete globalThis[mocksKey];
});

const id = "54e86508-e78b-4ff6-b3db-4116930b5027";

async function postRun() {
  const { POST } = await vite.ssrLoadModule("/app/api/analyses/[id]/run/route.ts");
  return POST(new Request(`https://example.test/api/analyses/${id}/run`, {
    method: "POST",
  }), { params: Promise.resolve({ id }) });
}

test("analysis run route preserves bounded retry timing for the client", async () => {
  globalThis[mocksKey] = {
    result: {
      outcome: "retry_queued",
      retryAfterSeconds: 23,
      detail: { job: { id, state: "queued" }, report: null },
    },
  };

  const response = await postRun();
  assert.equal(response.status, 202);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal(response.headers.get("Retry-After"), "23");
  assert.equal((await response.json()).runOutcome, "retry_queued");
});

test("analysis run route treats a recovered canceled job as terminal success", async () => {
  globalThis[mocksKey] = {
    result: {
      outcome: "terminal",
      detail: { job: { id, state: "canceled" }, report: null },
    },
  };

  const response = await postRun();
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Retry-After"), null);
  assert.equal((await response.json()).runOutcome, "terminal");
});
