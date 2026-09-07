import {
  EvidenceBundleV1Schema,
  PlayerSlotSchema,
  type EvidenceBundleV1,
  type EvidenceItemV1,
  type EvidenceUnit,
} from "@/lib/analysis/contracts";
import { AnalysisPublicError } from "@/lib/analysis/errors";

const SAFE_PREVIEW_METRICS = new Set([
  "duration",
  "radiant_score",
  "dire_score",
  "occurrences",
  "radiant_kills",
  "radiant_deaths",
  "radiant_gold_delta",
  "radiant_xp_delta",
  "dire_kills",
  "dire_deaths",
  "dire_gold_delta",
  "dire_xp_delta",
  "radiant_gold_advantage",
  "radiant_xp_advantage",
]);

export type ScanPreviewV1 = {
  schemaVersion: "scan-preview.v1";
  matchId: string;
  playerSlot: number;
  selectedEvidenceId: string;
  kind: "match" | "objective" | "fight" | "economy";
  atSeconds: number;
  team: "radiant" | "dire" | null;
  metrics: Array<{ metric: string; value: number; unit: EvidenceUnit }>;
};

function anchorSeconds(item: EvidenceItemV1, durationSeconds: number): number {
  if (item.time === null) return durationSeconds;
  return item.time.type === "point" ? item.time.seconds : item.time.endSeconds;
}

function signal(item: EvidenceItemV1, playerSlot: number): number {
  const directPlayerBonus = item.playerSlot === playerSlot ? 1_000_000 : 0;
  if (item.kind === "objective") return directPlayerBonus + 100_000;
  if (item.kind === "fight") {
    const deaths = item.values
      .filter((value) => value.metric === "radiant_deaths" || value.metric === "dire_deaths")
      .reduce((sum, value) => sum + Math.abs(value.value), 0);
    return directPlayerBonus + 50_000 + deaths;
  }
  if (item.kind === "economy") {
    const swing = item.values.reduce((largest, value) => Math.max(largest, Math.abs(value.value)), 0);
    return directPlayerBonus + 10_000 + Math.min(swing, 9_999);
  }
  return directPlayerBonus;
}

/** Selects exactly one bounded, factual moment. It performs no model call. */
export function buildScanPreview(bundleInput: EvidenceBundleV1, playerSlotInput: number): ScanPreviewV1 {
  const bundle = EvidenceBundleV1Schema.parse(bundleInput);
  const slotResult = PlayerSlotSchema.safeParse(playerSlotInput);
  if (!slotResult.success || !bundle.evidence.some((item) => item.kind === "player" && item.playerSlot === slotResult.data)) {
    throw new AnalysisPublicError(
      "INVALID_PLAYER_SLOT",
      "Выбранный слот игрока отсутствует в матче.",
      { httpStatus: 400, retryable: false, cause: slotResult.success ? undefined : slotResult.error },
    );
  }
  const playerSlot = slotResult.data;
  const timedCandidates = bundle.evidence.filter((item) =>
    item.time !== null
    && (item.playerSlot === null || item.playerSlot === playerSlot)
    && (item.kind === "objective" || item.kind === "fight" || item.kind === "economy"));
  const fallback = bundle.evidence.find((item) => item.id === "match.summary" && item.kind === "match");
  const selected = timedCandidates.sort((left, right) => {
    const signalDifference = signal(right, playerSlot) - signal(left, playerSlot);
    if (signalDifference !== 0) return signalDifference;
    const timeDifference = anchorSeconds(left, bundle.durationSeconds) - anchorSeconds(right, bundle.durationSeconds);
    if (timeDifference !== 0) return timeDifference;
    return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
  })[0] ?? fallback;
  if (!selected || (selected.kind !== "match" && selected.kind !== "objective" && selected.kind !== "fight" && selected.kind !== "economy")) {
    throw new AnalysisPublicError(
      "SCAN_PREVIEW_UNAVAILABLE",
      "Для этого матча недостаточно данных для бесплатного Scan.",
      { httpStatus: 400, retryable: false },
    );
  }

  return {
    schemaVersion: "scan-preview.v1",
    matchId: bundle.matchId,
    playerSlot,
    selectedEvidenceId: selected.id,
    kind: selected.kind,
    atSeconds: anchorSeconds(selected, bundle.durationSeconds),
    team: selected.team,
    metrics: selected.values
      .filter((value) => SAFE_PREVIEW_METRICS.has(value.metric))
      .slice(0, 12)
      .map((value) => ({ ...value })),
  };
}
