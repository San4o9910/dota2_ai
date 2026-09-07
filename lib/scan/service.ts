import type { AnalysisFetch } from "@/lib/analysis/opendota";
import { fetchOpenDotaMatch } from "@/lib/analysis/opendota";
import { buildEvidenceBundle } from "@/lib/analysis/normalizer";
import { normalizeOpenDotaMatch } from "@/lib/analysis/normalizer";
import { buildScanPreview } from "@/lib/analysis/scan-preview";
import type { ScanReadyResponse } from "@/lib/scan/contracts";
import type { ScanMatchCache } from "@/lib/scan/storage";

export type ScanServiceDependencies = {
  cache: ScanMatchCache;
  fetch?: AnalysisFetch;
  signal?: AbortSignal;
};

export async function runScan(
  request: {matchId:string;playerSlot:number},
  dependencies: ScanServiceDependencies,
): Promise<ScanReadyResponse> {
  let match = await dependencies.cache.get(request.matchId);
  if (!match) {
    const raw = await fetchOpenDotaMatch(request.matchId, {
      fetch: dependencies.fetch,
      signal: dependencies.signal,
    });
    match = normalizeOpenDotaMatch(raw);
    await dependencies.cache.put(match);
  }

  const artifacts = await buildEvidenceBundle(match,request.playerSlot);
  return {
    status: "ready",
    preview: buildScanPreview(artifacts.evidenceBundle, request.playerSlot),
  };
}
