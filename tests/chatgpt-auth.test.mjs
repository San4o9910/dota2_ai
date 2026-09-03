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

test("authenticated identity requires the stable site-scoped user id", async () => {
  const { parseChatGPTUserHeaders } = await vite.ssrLoadModule("/app/chatgpt-auth.ts");
  assert.equal(parseChatGPTUserHeaders(new Headers({
    "oai-authenticated-user-email": "player@example.test",
  })), null);

  const user = parseChatGPTUserHeaders(new Headers({
    "oai-authenticated-user-id": "site-user-123",
    "oai-authenticated-user-email": "player@example.test",
    "oai-authenticated-user-full-name": encodeURIComponent("Игрок NARMA"),
    "oai-authenticated-user-full-name-encoding": "percent-encoded-utf-8",
  }));
  assert.deepEqual(user, {
    id: "site-user-123",
    email: "player@example.test",
    fullName: "Игрок NARMA",
    displayName: "Игрок NARMA",
  });
});

test("untrusted name encoding falls back to email", async () => {
  const { parseChatGPTUserHeaders } = await vite.ssrLoadModule("/app/chatgpt-auth.ts");
  const user = parseChatGPTUserHeaders(new Headers({
    "oai-authenticated-user-id": "site-user-123",
    "oai-authenticated-user-email": "player@example.test",
    "oai-authenticated-user-full-name": "Injected%20Name",
    "oai-authenticated-user-full-name-encoding": "unknown",
  }));
  assert.equal(user.displayName, "player@example.test");
  assert.equal(user.fullName, null);
});
