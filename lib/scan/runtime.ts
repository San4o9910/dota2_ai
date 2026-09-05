import { env } from "cloudflare:workers";

import { parseScanRuntime, type ScanRuntimeEnvironment } from "@/lib/scan/runtime-config";

function runtimeEnvironment() {
  return env as unknown as ScanRuntimeEnvironment;
}

export function scanRuntimeEnabled(runtime: ScanRuntimeEnvironment = runtimeEnvironment()): boolean {
  return parseScanRuntime(runtime).ready;
}

export function getScanRuntime() {
  const runtime = runtimeEnvironment();
  const parsed = parseScanRuntime(runtime);
  if (!parsed.ready || !parsed.rateLimitSecret || !runtime.DB) return null;
  return {
    db: runtime.DB as D1Database,
    rateLimitSecret: parsed.rateLimitSecret,
  };
}
