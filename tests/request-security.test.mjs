import assert from "node:assert/strict";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const root = fileURLToPath(new URL("..", import.meta.url));
const vite = await createServer({
  appType: "custom",
  configFile: false,
  root,
  resolve: { alias: { "@": root } },
  server: { middlewareMode: true },
});

after(async () => vite.close());

test("mutation guard accepts only the request origin", async () => {
  const { isSameOriginRequest } = await vite.ssrLoadModule(
    "/lib/security/same-origin.ts",
  );

  assert.equal(isSameOriginRequest(new Request("https://narma.test/api/account", {
    method: "POST",
    headers: { Origin: "https://narma.test" },
  })), true);
  assert.equal(isSameOriginRequest(new Request("https://narma.test/api/account", {
    method: "POST",
    headers: { Origin: "https://attacker.test" },
  })), false);
  assert.equal(isSameOriginRequest(new Request("https://narma.test/api/account", {
    method: "POST",
  })), false);
});

test("JSON handlers reject null and arrays before reading fields", async () => {
  const { isJsonObject } = await vite.ssrLoadModule("/lib/security/json.ts");
  assert.equal(isJsonObject(null), false);
  assert.equal(isJsonObject([]), false);
  assert.equal(isJsonObject("payload"), false);
  assert.equal(isJsonObject({ event: "payment.succeeded" }), true);
});
