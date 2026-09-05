import { createHash } from "node:crypto";
import { access, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SECURITY_HEADERS } from "../config/security-headers.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const zeroDatabaseId = "00000000-0000-4000-8000-000000000000";
const requiredD1Binding = "DB";
const nonzeroDatabaseUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function invariant(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function exists(relativePath) {
  try {
    await access(path.join(root, relativePath));
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

async function requiredFile(relativePath) {
  invariant(await exists(relativePath), `Required package file is missing: ${relativePath}`);
  return readFile(path.join(root, relativePath));
}

async function requiredJson(relativePath) {
  const contents = await requiredFile(relativePath);
  try {
    return JSON.parse(contents.toString("utf8"));
  } catch (error) {
    throw new Error(`Invalid JSON in ${relativePath}: ${error.message}`);
  }
}

async function listFiles(relativeDirectory) {
  const absoluteDirectory = path.join(root, relativeDirectory);
  const files = [];

  async function visit(directory, prefix) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = path.join(directory, entry.name);
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        await visit(absolute, relative);
      } else if (entry.isFile()) {
        files.push(relative);
      } else {
        throw new Error(`Unsupported non-file package entry: ${relativeDirectory}/${relative}`);
      }
    }
  }

  await visit(absoluteDirectory, "");
  return files;
}

async function sha256(relativePath) {
  return createHash("sha256")
    .update(await requiredFile(relativePath))
    .digest("hex");
}

async function verifyCopiedTree(sourceDirectory, packagedDirectory) {
  const sourceFiles = await listFiles(sourceDirectory);
  const packagedFiles = await listFiles(packagedDirectory);
  invariant(sourceFiles.length > 0, `Source package tree is empty: ${sourceDirectory}`);
  invariant(
    JSON.stringify(packagedFiles) === JSON.stringify(sourceFiles),
    `Packaged tree differs from source: ${packagedDirectory}`,
  );

  for (const relative of sourceFiles) {
    const sourceHash = await sha256(`${sourceDirectory}/${relative}`);
    const packagedHash = await sha256(`${packagedDirectory}/${relative}`);
    invariant(sourceHash === packagedHash, `Packaged file hash differs: ${packagedDirectory}/${relative}`);
  }
  return sourceFiles;
}

function isPlaceholder(value) {
  return typeof value === "string"
    && (value.includes(zeroDatabaseId) || /(?:change[-_ ]?me|placeholder|example|<[^>]+>)/i.test(value));
}

export function verifyD1PackageContract(hosting, d1Bindings) {
  invariant(
    hosting?.d1 === requiredD1Binding,
    `.openai/hosting.json d1 must equal ${requiredD1Binding}`,
  );
  invariant(
    Array.isArray(d1Bindings) && d1Bindings.length === 1,
    "Built Worker must contain exactly one D1 binding",
  );

  const [binding] = d1Bindings;
  invariant(
    binding && typeof binding === "object" && binding.binding === requiredD1Binding,
    `Built Worker D1 binding must equal ${requiredD1Binding}`,
  );

  const databaseId = binding.database_id;
  const validNonzeroUuid = typeof databaseId === "string"
    && nonzeroDatabaseUuid.test(databaseId)
    && databaseId.toLowerCase() !== zeroDatabaseId;
  invariant(
    databaseId === zeroDatabaseId || validNonzeroUuid,
    "Built Sites D1 binding database_id must be the exact Sites placeholder or a valid nonzero UUID",
  );

  return binding;
}

async function verifyNoDeployablePlaceholderConfig() {
  for (const name of ["wrangler.json", "wrangler.jsonc", "wrangler.toml"]) {
    if (!(await exists(name))) continue;
    const contents = (await requiredFile(name)).toString("utf8");
    invariant(!isPlaceholder(contents), `${name} contains a placeholder and must not be deployable`);
  }

  const typeConfig = (await requiredFile("wrangler.types.jsonc")).toString("utf8");
  for (const key of ["name", "main", "account_id", "routes", "workers_dev", "d1_databases", "r2_buckets"]) {
    invariant(
      !new RegExp(`"${key}"\\s*:`).test(typeConfig),
      `wrangler.types.jsonc must remain type-generation-only; found deployment key ${key}`,
    );
  }
  invariant(!typeConfig.includes(zeroDatabaseId), "wrangler.types.jsonc must not contain a placeholder database ID");
}

async function verifyPackage() {
  await verifyNoDeployablePlaceholderConfig();

  const sourceHostingBytes = await requiredFile(".openai/hosting.json");
  const packagedHostingBytes = await requiredFile("dist/.openai/hosting.json");
  invariant(
    sourceHostingBytes.equals(packagedHostingBytes),
    "dist/.openai/hosting.json must be an exact copy of the source Sites metadata",
  );

  const hosting = await requiredJson(".openai/hosting.json");
  invariant(
    typeof hosting.project_id === "string" && hosting.project_id.length > 0 && !isPlaceholder(hosting.project_id),
    ".openai/hosting.json must contain a non-placeholder Sites project_id",
  );
  invariant(
    hosting.d1 === requiredD1Binding,
    `.openai/hosting.json d1 must equal ${requiredD1Binding}`,
  );
  invariant(
    hosting.r2 === null || (typeof hosting.r2 === "string" && /^[A-Za-z_][A-Za-z0-9_]*$/.test(hosting.r2)),
    ".openai/hosting.json r2 must be null or a binding name",
  );

  await requiredFile("dist/server/index.js");
  await requiredFile("dist/client/_headers");
  const clientAssets = await listFiles("dist/client/_next/static");
  invariant(
    clientAssets.length > 0,
    "dist/client/_next/static must contain the compiled client assets",
  );

  const clientManifest = await requiredJson("dist/client/.vite/manifest.json");
  const manifestAssetPaths = new Set();
  for (const [source, entry] of Object.entries(clientManifest)) {
    invariant(entry && typeof entry === "object", `Invalid client manifest entry: ${source}`);
    invariant(typeof entry.file === "string", `Client manifest entry is missing its file: ${source}`);

    for (const field of ["css", "assets"]) {
      invariant(
        entry[field] === undefined || Array.isArray(entry[field]),
        `Client manifest ${field} must be an array: ${source}`,
      );
    }
    for (const relative of [entry.file, ...(entry.css ?? []), ...(entry.assets ?? [])]) {
      invariant(typeof relative === "string", `Client manifest contains a non-string asset: ${source}`);
      invariant(
        !relative.includes("\\")
          && relative === path.posix.normalize(relative)
          && relative.startsWith("_next/static/"),
        `Client manifest asset must stay inside _next/static: ${relative}`,
      );
      await requiredFile(`dist/client/${relative}`);
      manifestAssetPaths.add(relative);
    }

    for (const field of ["imports", "dynamicImports"]) {
      invariant(
        entry[field] === undefined || Array.isArray(entry[field]),
        `Client manifest ${field} must be an array: ${source}`,
      );
      for (const imported of entry[field] ?? []) {
        invariant(
          typeof imported === "string" && Object.hasOwn(clientManifest, imported),
          `Client manifest references an unknown ${field} entry: ${imported}`,
        );
      }
    }
  }
  invariant(manifestAssetPaths.size > 0, "Client manifest must reference compiled client assets");

  const clientEntryManifest = await requiredJson("dist/client/vinext-client-entry-manifest.json");
  invariant(
    typeof clientEntryManifest.appBrowserEntry === "string"
      && manifestAssetPaths.has(clientEntryManifest.appBrowserEntry),
    "Vinext client entry manifest must reference a compiled client asset",
  );

  const wrangler = await requiredJson("dist/server/wrangler.json");
  invariant(typeof wrangler.main === "string" && wrangler.main.length > 0, "Built Wrangler metadata needs an entrypoint");
  const serverDirectory = path.join(root, "dist/server");
  const workerEntrypoint = path.resolve(serverDirectory, wrangler.main);
  invariant(
    workerEntrypoint.startsWith(`${serverDirectory}${path.sep}`),
    "Built Worker entrypoint must stay inside dist/server",
  );
  invariant(await exists(path.relative(root, workerEntrypoint)), `Built Worker entrypoint is missing: ${wrangler.main}`);

  const assetDirectory = path.resolve(serverDirectory, wrangler.assets?.directory ?? "");
  invariant(assetDirectory === path.join(root, "dist/client"), "Built Worker assets must resolve to dist/client");

  const d1Bindings = wrangler.d1_databases;
  const expectedBinding = verifyD1PackageContract(hosting, d1Bindings);
  const migrationFiles = await verifyCopiedTree("drizzle", "dist/.openai/drizzle");
  invariant(migrationFiles.some((name) => name.endsWith(".sql")), "At least one D1 migration must be packaged");
  invariant(migrationFiles.includes("meta/_journal.json"), "The D1 migration journal must be packaged");

  if (expectedBinding.database_id === zeroDatabaseId) {
    console.log("Recognized the generated Sites-only D1 placeholder; direct Wrangler deployment remains prohibited.");
  }

  const vinextManifest = await requiredJson("dist/server/vinext-server.json");
  invariant(
    typeof vinextManifest.prerenderSecret === "string" && vinextManifest.prerenderSecret.length >= 32,
    "Vinext server manifest must contain a generated prerender secret",
  );
  for (const relative of await listFiles("dist/client")) {
    const contents = await requiredFile(`dist/client/${relative}`);
    invariant(
      !contents.includes(vinextManifest.prerenderSecret),
      `Vinext prerender secret leaked into client output: dist/client/${relative}`,
    );
  }

  const generatedHeaders = (await requiredFile("dist/client/_headers")).toString("utf8");
  invariant(
    /^\/_next\/static\/\*$/m.test(generatedHeaders),
    "Generated _headers must cover Vinext's canonical hashed asset path",
  );
  invariant(/max-age=31536000,\s*immutable/i.test(generatedHeaders), "Hashed assets must keep immutable caching");
  invariant(/^\/\*$/m.test(generatedHeaders), "Generated _headers must cover static files that bypass the Worker");
  for (const { key, value } of SECURITY_HEADERS) {
    invariant(generatedHeaders.includes(`  ${key}: ${value}`), `Static asset headers are missing ${key}`);
  }

  const serverJavaScript = (
    await Promise.all(
      (await listFiles("dist/server"))
        .filter((name) => name.endsWith(".js"))
        .map((name) => requiredFile(`dist/server/${name}`)),
    )
  ).map((contents) => contents.toString("utf8")).join("\n");
  for (const { key, value } of SECURITY_HEADERS) {
    invariant(serverJavaScript.includes(key), `Built server is missing security header ${key}`);
    invariant(serverJavaScript.includes(value), `Built server is missing the configured value for ${key}`);
  }

  console.log(
    `Package contract verified: ${clientAssets.length} client assets, ${d1Bindings.length} D1 binding(s), Sites metadata and migrations intact.`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await verifyPackage();
  } catch (error) {
    console.error(`Package verification failed: ${error.message}`);
    process.exitCode = 1;
  }
}
