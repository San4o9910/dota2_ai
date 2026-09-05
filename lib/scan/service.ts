import type { AnalysisFetch } from "@/lib/analysis/opendota";
import { fetchOpenDotaMatch } from "@/lib/analysis/opendota";
import { buildEvidenceBundle } from "@/lib/analysis/normalizer";
import { normalizeOpenDotaMatch } from "@/lib/analysis/normalizer";
import { buildScanPreview } from "@/lib/analysis/scan-preview";
import {
  ScanRosterItemSchema,
  type ScanRequest,
  type ScanSuccessResponse,
} from "@/lib/scan/contracts";
import type { ScanMatchCache } from "@/lib/scan/storage";

export type ScanServiceDependencies = {
  cache: ScanMatchCache;
  fetch?: AnalysisFetch;
  signal?: AbortSignal;
};

export async function runScan(
  request: ScanRequest,
  dependencies: ScanServiceDependencies,
): Promise<ScanSuccessResponse> {
  let match = await dependencies.cache.get(request.matchId);
  if (!match) {
    const raw = await fetchOpenDotaMatch(request.matchId, {
      fetch: dependencies.fetch,
      signal: dependencies.signal,
    });
    match = normalizeOpenDotaMatch(raw);
    await dependencies.cache.put(match);
  }

  if (request.playerSlot === undefined) {
    const players = match.players.map((player) => ScanRosterItemSchema.parse({
      playerSlot: player.playerSlot,
      heroId: player.heroId,
      side: player.isRadiant ? "radiant" : "dire",
      kills: player.kills,
      deaths: player.deaths,
      assists: player.assists,
    }));
    return {
      status: "choose_player",
      match: {
        matchId: match.matchId,
        durationSeconds: match.durationSeconds,
      },
      players,
    };
  }

  const artifacts = await buildEvidenceBundle(match);
  return {
    status: "ready",
    preview: buildScanPreview(artifacts.evidenceBundle, request.playerSlot),
  };
}
