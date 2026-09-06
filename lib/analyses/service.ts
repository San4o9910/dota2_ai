import { AnalysisError } from "@/lib/analysis/errors";
import { buildEvidenceBundle, normalizeOpenDotaMatch } from "@/lib/analysis/normalizer";
import { generateAnalysisReport } from "@/lib/analysis/openai";
import { fetchOpenDotaMatch, type AnalysisFetch } from "@/lib/analysis/opendota";
import { NARMA_COACHING_METHOD_VERSION } from "@/lib/coaching/method";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";
import { playerError, type PlayerTarget } from "@/lib/dota/player-identity";
import { AnalysisRouteError } from "@/lib/analyses/errors";
import {
  D1AnalysisStore,
  type ClaimAnalysisResult,
} from "@/lib/analyses/store";
import {
  D1ScanMatchCache,
  SCAN_NORMALIZER_VERSION,
  type ScanMatchCache,
} from "@/lib/scan/storage";

export const ANALYSIS_PROMPT_VERSION = NARMA_COACHING_METHOD_VERSION;

export type RunAnalysisDependencies = {
  store: D1AnalysisStore;
  cache: ScanMatchCache;
  apiKey: string;
  model: string;
  allowedModels: readonly string[];
  authorizeTarget: (userId: string, matchId: string, playerSlot: number) => Promise<PlayerTarget>;
  fetch?: AnalysisFetch;
  signal?: AbortSignal;
};

export type RunAnalysisResult = {
  outcome: ClaimAnalysisResult["outcome"] | "completed" | "retry_queued" | "failed" | "lease_lost";
  detail: Awaited<ReturnType<D1AnalysisStore["getOwned"]>>;
  retryAfterSeconds?: number;
};

function safeRunnerFailure(error: unknown) {
  if (error instanceof AnalysisRouteError) return {code:error.code,message:error.message,retryable:false};
  if (error instanceof AnalysisError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  return {
    code: "ANALYSIS_INTERNAL_ERROR",
    message: "Не удалось завершить анализ. Попробуйте ещё раз.",
    retryable: true,
  };
}

/** Runs a leased job with a request-independent bounded deadline. The route
 * retains work with waitUntil through next/server after(). D1 remains the
 * durable job journal; this does not claim a provisioned autonomous queue. */
export async function runOwnedAnalysis(
  userId: string,
  analysisId: string,
  dependencies: RunAnalysisDependencies,
): Promise<RunAnalysisResult> {
  const claimResult = await dependencies.store.claimOwned(userId, analysisId);
  if (claimResult.outcome !== "claimed") {
    return {
      outcome: claimResult.outcome,
      detail: await dependencies.store.getOwned(userId, analysisId),
      ...(claimResult.outcome === "busy" && claimResult.retryAfterSeconds !== undefined
        ? { retryAfterSeconds: claimResult.retryAfterSeconds }
        : {}),
    };
  }

  const { claim } = claimResult;
  const started=Date.now();
  console.info(JSON.stringify({event:"analysis_attempt_started",jobId:analysisId,attempt:claim.attempt}));
  try {
    const target = await dependencies.authorizeTarget(userId,claim.matchId,claim.playerSlot);
    let match = await dependencies.store.getReadyReplay?.(userId,claim.matchId) ?? await dependencies.cache.get(claim.matchId);
    if (!match) {
      const raw = await fetchOpenDotaMatch(claim.matchId, {
        fetch: dependencies.fetch,
        signal: dependencies.signal,
      });
      match = normalizeOpenDotaMatch(raw);
      await dependencies.cache.put(match);
    }

    if (match.matchId !== target.matchId || !match.players.some(player => player.playerSlot === target.playerSlot && player.heroId === target.heroId))
      throw playerError("DOTA_TARGET_MISMATCH","Данные реплея не совпали с закреплённым игроком.",403);
    const artifacts = await buildEvidenceBundle(match,claim.playerSlot);
    const report = await generateAnalysisReport({
      apiKey: dependencies.apiKey,
      model: dependencies.model,
      allowedModels: dependencies.allowedModels,
      evidenceBundle: artifacts.evidenceBundle,
      evidenceHash: artifacts.evidenceHash,
      playerSlot: claim.playerSlot,
      fetch: dependencies.fetch,
      signal: dependencies.signal,
    });
    const completed = await dependencies.store.complete(claim, {
      evidenceBundle: artifacts.evidenceBundle,
      evidenceHash: artifacts.evidenceHash,
      report,
      normalizerVersion: SCAN_NORMALIZER_VERSION,
      normalizedMatch: match,
      model: dependencies.model,
      promptVersion: ANALYSIS_PROMPT_VERSION,
    });
    console.info(JSON.stringify({event:"analysis_attempt_finished",jobId:analysisId,elapsedMs:Date.now()-started,outcome:completed ? "ready" : "lease_lost"}));
    return {
      outcome: completed ? "completed" : "lease_lost",
      detail: await dependencies.store.getOwned(userId, analysisId),
    };
  } catch (error) {
    console.warn(JSON.stringify({event:"analysis_attempt_failed",jobId:analysisId,elapsedMs:Date.now()-started,code:safeRunnerFailure(error).code}));
    const resolution = await dependencies.store.fail(claim, safeRunnerFailure(error));
    return {
      outcome: resolution.outcome === "queued"
        ? "retry_queued"
        : resolution.outcome === "failed"
          ? "failed"
          : "lease_lost",
      detail: await dependencies.store.getOwned(userId, analysisId),
      ...(resolution.outcome === "queued"
        ? { retryAfterSeconds: resolution.retryAfterSeconds }
        : {}),
    };
  }
}

export function analysisRunnerDependencies(
  db: D1Database,
  config: { apiKey: string; model: string; allowedModels: readonly string[] },
  options: { signal?: AbortSignal } = {},
): RunAnalysisDependencies {
  return {
    store: new D1AnalysisStore(db),
    cache: new D1ScanMatchCache(db),
    apiKey: config.apiKey,
    model: config.model,
    allowedModels: config.allowedModels,
    signal: options.signal,
    authorizeTarget: (userId,matchId,playerSlot) => new D1PlayerBindingStore(db).assertTarget(userId,matchId,playerSlot),
  };
}
