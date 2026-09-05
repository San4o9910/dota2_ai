import { env } from "cloudflare:workers";

import {
  parseAnalysisRuntime,
  type AnalysisRuntimeEnvironment,
} from "@/lib/analyses/runtime-config";

type RuntimeEnvironment = AnalysisRuntimeEnvironment & { DB?: D1Database };

function runtimeEnvironment() {
  return env as unknown as RuntimeEnvironment;
}

export function analysisRuntimeAcceptingJobs(
  runtime: AnalysisRuntimeEnvironment = runtimeEnvironment(),
) {
  return parseAnalysisRuntime(runtime).acceptingJobs && !!(runtime as RuntimeEnvironment).DB;
}

export function getAnalysisRuntime() {
  const runtime = runtimeEnvironment();
  const parsed = parseAnalysisRuntime(runtime);
  return {
    ...parsed,
    acceptingJobs: parsed.acceptingJobs && !!runtime.DB,
    fulfillmentReady: parsed.fulfillmentReady && !!runtime.DB,
    db: runtime.DB ?? null,
  };
}

