import { spawnSync } from "node:child_process";

import { verifyVendoredImageSize } from "./patch-vinext-image-size.mjs";

await verifyVendoredImageSize();
console.log("Vinext vendored image-size security patch: verified");

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const auditTimeoutMs = 90_000;
const result = spawnSync(
  npmCommand,
  ["audit", "--json", "--audit-level=high"],
  {
    encoding: "utf8",
    env: { ...process.env, npm_config_audit: "true" },
    killSignal: "SIGTERM",
    maxBuffer: 20 * 1024 * 1024,
    timeout: auditTimeoutMs,
  },
);

if (result.stderr) {
  process.stderr.write(result.stderr);
}
if (result.error?.code === "ETIMEDOUT") {
  throw new Error(`npm audit timed out after ${auditTimeoutMs / 1000}s; advisory availability is unverified`);
}
if (result.error) {
  throw result.error;
}
if (result.signal) {
  throw new Error(`npm audit terminated by signal ${result.signal}`);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  if (result.stdout) {
    process.stderr.write(result.stdout);
  }
  throw new Error("npm audit did not return a JSON report; registry/network availability is unverified");
}

if (report.error || !report.metadata?.vulnerabilities) {
  const summary = report.error?.summary ?? report.message ?? "missing vulnerability metadata";
  throw new Error(`npm audit could not verify advisories: ${summary}`);
}

const counts = report.metadata.vulnerabilities;
const orderedSeverities = ["info", "low", "moderate", "high", "critical"];
console.log(
  `Dependency advisory report: ${orderedSeverities
    .map((severity) => `${severity}=${counts[severity] ?? 0}`)
    .join(", ")}`,
);

const releaseFindings = Object.entries(report.vulnerabilities ?? {})
  .filter(([, finding]) => ["high", "critical"].includes(finding.severity))
  .map(([name, finding]) => `${name} (${finding.severity})`)
  .sort();

if (releaseFindings.length > 0) {
  console.error("High/critical dependency findings block the release:");
  for (const finding of releaseFindings) {
    console.error(`- ${finding}`);
  }
}

if (![0, 1].includes(result.status)) {
  throw new Error(`npm audit exited unexpectedly with status ${result.status}`);
}
if (result.status === 1 && releaseFindings.length === 0) {
  throw new Error("npm audit failed without a high/critical advisory; treating this as an audit transport/tool failure");
}

// Fail closed. Any temporary exception must be reviewed and represented by a
// narrow, expiring code change rather than silently teaching CI to ignore it.
process.exit(releaseFindings.length > 0 ? 1 : 0);
