import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  EXPECTED_VINEXT_VERSION,
  PATCHED_SHA256,
  PRISTINE_SHA256,
  VENDORED_IMAGE_SIZE_REPLACEMENTS,
  patchVendoredImageSize,
  verifyVendoredImageSize,
} from "../scripts/patch-vinext-image-size.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const installedManifestPath = path.join(root, "node_modules/vinext/package.json");
const installedBundlePath = path.join(
  root,
  "node_modules/vinext/dist/deps/.pnpm/image-size@2.0.2/deps/image-size/dist/index.js",
);

function sha256(source) {
  return createHash("sha256").update(source).digest("hex");
}

test("vendored image-size patch is exact, idempotent, and fails closed on drift", async (t) => {
  assert.equal(await verifyVendoredImageSize(), "verified");
  assert.equal(await patchVendoredImageSize(), "already-patched");
  const patchedSource = await readFile(installedBundlePath, "utf8");
  assert.equal(sha256(patchedSource), PATCHED_SHA256);

  let pristineSource = patchedSource;
  for (const [before, after] of VENDORED_IMAGE_SIZE_REPLACEMENTS) {
    assert.equal(pristineSource.split(after).length - 1, 1);
    pristineSource = pristineSource.replace(after, before);
  }
  assert.equal(sha256(pristineSource), PRISTINE_SHA256);

  const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "vinext-image-size-patch-"));
  t.after(() => rm(temporaryRoot, { force: true, recursive: true }));
  const manifestPath = path.join(temporaryRoot, "package.json");
  const bundlePath = path.join(temporaryRoot, "index.js");
  await writeFile(
    manifestPath,
    `${JSON.stringify({ name: "vinext", version: EXPECTED_VINEXT_VERSION })}\n`,
  );
  await writeFile(bundlePath, pristineSource);

  await assert.rejects(
    verifyVendoredImageSize({ manifestPath, bundlePath }),
    /security patch is missing/,
  );
  assert.equal(await patchVendoredImageSize({ manifestPath, bundlePath }), "patched");
  assert.equal(await verifyVendoredImageSize({ manifestPath, bundlePath }), "verified");
  assert.equal(sha256(await readFile(bundlePath, "utf8")), PATCHED_SHA256);
  assert.equal(await patchVendoredImageSize({ manifestPath, bundlePath }), "already-patched");

  await writeFile(bundlePath, `${patchedSource}\n`);
  await assert.rejects(
    patchVendoredImageSize({ manifestPath, bundlePath }),
    /Refusing to patch unrecognized vendored image-size bundle/,
  );

  await writeFile(
    manifestPath,
    `${JSON.stringify({ name: "vinext", version: "unexpected" })}\n`,
  );
  await assert.rejects(
    patchVendoredImageSize({ manifestPath, bundlePath }),
    /Refusing to patch vinext unexpected/,
  );
});

test("vendored parser terminates on the three zero-length advisory payloads", () => {
  const payloads = {
    icns: "69636e73000000106973333200000000",
    heif: [
      "00000010667479706176696600000000",
      "000000246d65746100000000",
      "0000000869707270",
      "000000146970636f",
      "0000000069737065",
      "00000000000000000000000000000000",
    ].join(""),
    jxl: [
      "0000000c4a584c200d0a870a",
      "00000014667479706a786c20000000006a786c20",
      "000000006a786c70",
    ].join(""),
  };
  const childSource = `
    const { imageSize } = await import(process.argv[1]);
    const payloads = ${JSON.stringify(payloads)};
    try {
      imageSize(Buffer.from(payloads[process.argv[2]], "hex"));
    } catch {}
    process.stdout.write("settled");
  `;
  const bundleUrl = pathToFileURL(installedBundlePath).href;

  for (const payloadName of Object.keys(payloads)) {
    const result = spawnSync(
      process.execPath,
      ["--input-type=module", "--eval", childSource, bundleUrl, payloadName],
      { encoding: "utf8", timeout: 2_000 },
    );
    assert.equal(result.error, undefined, `${payloadName} parser exceeded the hard timeout`);
    assert.equal(result.signal, null, `${payloadName} parser was terminated by ${result.signal}`);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, "settled");
  }
});

test("Vinext package manifest remains pinned to the audited patch target", async () => {
  const manifest = JSON.parse(await readFile(installedManifestPath, "utf8"));
  assert.equal(manifest.version, EXPECTED_VINEXT_VERSION);
});
