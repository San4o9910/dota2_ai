import { createHash } from "node:crypto";
import { readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

// Vinext beta.6+ vendors image-size instead of declaring it in the npm graph.
// image-size has no published fix for GHSA-5p2g-fcmc-qvqq or
// GHSA-w3rx-r6r6-pgpr. These progress guards include the unpublished upstream
// HEIF/JXL fix and the equivalent ICNS fix, while hashes make package drift
// fail closed. Remove this patch when Vinext ships a fixed vendored parser.
export const EXPECTED_VINEXT_VERSION = "1.0.0-beta.9";
export const PRISTINE_SHA256 = "456ef3528be51418bebdd975aac4b6f4345610964166d1492220b35d686c8d15";
export const PATCHED_SHA256 = "ad25ae3778c2411cbf37e128cb5a8e7a5f383bf246c68a6b6c1d499c8b90530b";
export const VENDORED_IMAGE_SIZE_REPLACEMENTS = [
  [
    "currentOffset = ispeBox.offset + ispeBox.size;",
    "currentOffset = ispeBox.offset + (ispeBox.size > 0 ? ispeBox.size : 8);",
  ],
  [
    "imageOffset += imageHeader[1];",
    "imageOffset += imageHeader[1] > 0 ? imageHeader[1] : 8;",
  ],
  [
    "offset = jxlpBox.offset + jxlpBox.size;",
    "offset = jxlpBox.offset + (jxlpBox.size > 0 ? jxlpBox.size : 8);",
  ],
];

const defaultManifestPath = path.join(root, "node_modules/vinext/package.json");
const defaultBundlePath = path.join(
  root,
  "node_modules/vinext/dist/deps/.pnpm/image-size@2.0.2/deps/image-size/dist/index.js",
);

function sha256(source) {
  return createHash("sha256").update(source).digest("hex");
}

async function readPatchTarget({
  manifestPath = defaultManifestPath,
  bundlePath = defaultBundlePath,
} = {}) {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.name !== "vinext") {
    throw new Error(`Refusing to patch unexpected package ${manifest.name ?? "unknown"}`);
  }
  if (manifest.version !== EXPECTED_VINEXT_VERSION) {
    throw new Error(
      `Refusing to patch vinext ${manifest.version ?? "unknown"}; expected ${EXPECTED_VINEXT_VERSION}`,
    );
  }

  const source = await readFile(bundlePath, "utf8");
  return { bundlePath, source };
}

export async function verifyVendoredImageSize(options = {}) {
  const { source } = await readPatchTarget(options);
  const actualHash = sha256(source);
  if (actualHash !== PATCHED_SHA256) {
    throw new Error(`Vinext vendored image-size security patch is missing (${actualHash})`);
  }
  return "verified";
}

export async function patchVendoredImageSize(options = {}) {
  const { bundlePath, source: originalSource } = await readPatchTarget(options);

  let source = originalSource;
  const originalHash = sha256(source);
  if (originalHash === PATCHED_SHA256) {
    return "already-patched";
  }
  if (originalHash !== PRISTINE_SHA256) {
    throw new Error(`Refusing to patch unrecognized vendored image-size bundle (${originalHash})`);
  }

  for (const [before, after] of VENDORED_IMAGE_SIZE_REPLACEMENTS) {
    const matches = source.split(before).length - 1;
    if (matches !== 1) {
      throw new Error(`Expected exactly one vendored image-size patch site, found ${matches}: ${before}`);
    }
    source = source.replace(before, after);
  }

  const patchedHash = sha256(source);
  if (patchedHash !== PATCHED_SHA256) {
    throw new Error(`Patched vendored image-size hash mismatch (${patchedHash})`);
  }
  const temporaryBundlePath = `${bundlePath}.security-patch-${process.pid}`;
  await writeFile(temporaryBundlePath, source, "utf8");
  await rename(temporaryBundlePath, bundlePath);
  await verifyVendoredImageSize(options);
  return "patched";
}

const isMain = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  try {
    const action = process.argv[2] ?? "--patch";
    if (!["--patch", "--verify"].includes(action)) {
      throw new Error(`Unsupported action ${action}`);
    }
    const result = action === "--verify"
      ? await verifyVendoredImageSize()
      : await patchVendoredImageSize();
    console.log(`Vinext vendored image-size security patch: ${result}`);
  } catch (error) {
    console.error(`Vinext vendored image-size security patch failed: ${error.message}`);
    process.exitCode = 1;
  }
}
