import { spawnSync } from "node:child_process";
import { readdir } from "node:fs/promises";
import path from "node:path";

const testsDirectory = path.resolve("tests");
const packageTests = new Set([
  "rendered-html.test.mjs",
  "ui-components.test.mjs",
]);

const entries = await readdir(testsDirectory, { withFileTypes: true });
const discoveredTests = entries
  .filter((entry) => entry.isFile() && entry.name.endsWith(".test.mjs"))
  .map((entry) => entry.name)
  .sort();

for (const packageTest of packageTests) {
  if (!discoveredTests.includes(packageTest)) {
    throw new Error(`Expected build-dependent test is missing: tests/${packageTest}`);
  }
}

const unitTests = discoveredTests
  .filter((name) => !packageTests.has(name))
  .map((name) => path.join("tests", name));

if (unitTests.length === 0) {
  throw new Error("No unit tests were discovered in tests/*.test.mjs");
}

console.log(`Running ${unitTests.length} unit test files; package-output tests run after build.`);
const result = spawnSync(
  process.execPath,
  ["--test", "--test-concurrency=1", ...unitTests],
  { stdio: "inherit" },
);

if (result.error) {
  throw result.error;
}
if (result.signal) {
  console.error(`Unit tests terminated by signal ${result.signal}.`);
  process.exit(1);
}
process.exit(result.status ?? 1);
