import { canonicalSha256 } from "@/lib/analysis/canonical-json";
import {
  AnalysisReportV1Schema,
  EvidenceBundleV1Schema,
  PlayerSlotSchema,
  type AnalysisReportV1,
  type EvidenceBundleV1,
  type EvidenceTimeV1,
} from "@/lib/analysis/contracts";
import { AnalysisDependencyError } from "@/lib/analysis/errors";
import { compileCoachingPresentation } from "@/lib/analysis/coaching-presentation";

function groundingFailure(message: string, cause?: unknown) {
  return new AnalysisDependencyError(
    "openai",
    "OPENAI_REPORT_UNGROUNDED",
    message,
    { cause, httpStatus: 503, retryable: false },
  );
}

function withinDuration(time: EvidenceTimeV1, durationSeconds: number): boolean {
  if (time === null) return true;
  if (time.type === "point") return time.seconds <= durationSeconds;
  return time.startSeconds <= durationSeconds && time.endSeconds <= durationSeconds;
}

function timeBounds(time: Exclude<EvidenceTimeV1, null>): [number, number] {
  return time.type === "point"
    ? [time.seconds, time.seconds]
    : [time.startSeconds, time.endSeconds];
}

function sameTime(left: Exclude<EvidenceTimeV1, null>, right: Exclude<EvidenceTimeV1, null>): boolean {
  const [leftStart, leftEnd] = timeBounds(left);
  const [rightStart, rightEnd] = timeBounds(right);
  return leftStart === rightStart && leftEnd === rightEnd;
}

export type GroundedReportOptions = {
  evidenceHash: string;
  playerSlot: number | null;
};

/**
 * Performs semantic checks that JSON Schema cannot express. Hashes, references,
 * exact numeric claims, slots and time claims all fail closed before a report
 * can be persisted.
 */
export async function validateGroundedReport(
  reportInput: AnalysisReportV1,
  bundleInput: EvidenceBundleV1,
  options: GroundedReportOptions,
): Promise<AnalysisReportV1> {
  const report = AnalysisReportV1Schema.parse(reportInput);
  const bundle = EvidenceBundleV1Schema.parse(bundleInput);
  const playerSlot = options.playerSlot === null ? null : PlayerSlotSchema.parse(options.playerSlot);
  const actualEvidenceHash = await canonicalSha256(bundle);

  if (actualEvidenceHash !== options.evidenceHash || report.evidenceHash !== actualEvidenceHash) {
    throw groundingFailure("Ответ модели относится к другой версии доказательств.");
  }
  if (report.matchId !== bundle.matchId) {
    throw groundingFailure("Ответ модели относится к другому матчу.");
  }
  if (report.playerSlot !== playerSlot) {
    throw groundingFailure("Ответ модели относится к другому игроку.");
  }

  const evidenceById = new Map(bundle.evidence.map((evidence) => [evidence.id, evidence]));
  if (playerSlot !== null && !bundle.evidence.some((item) => item.kind === "player" && item.playerSlot === playerSlot)) {
    throw groundingFailure("Выбранный слот игрока отсутствует в доказательствах матча.");
  }

  for (const item of report.items) {
    const referenced = item.evidenceIds.map((id) => evidenceById.get(id));
    if (referenced.some((evidence) => evidence === undefined)) {
      throw groundingFailure("Ответ модели ссылается на неизвестное доказательство.");
    }
    const knownEvidence = referenced.filter((evidence) => evidence !== undefined);
    for (const claim of item.claims) {
      if (!item.evidenceIds.includes(claim.evidenceId)) {
        throw groundingFailure("Числовое утверждение не ссылается на указанное доказательство.");
      }
      const claimEvidence = evidenceById.get(claim.evidenceId);
      if (!claimEvidence) {
        throw groundingFailure("Числовое утверждение ссылается на неизвестное доказательство.");
      }
      const exactValueExists = claimEvidence.values.some((value) =>
        value.metric === claim.metric
        && value.value === claim.value
        && value.unit === claim.unit);
      if (!exactValueExists) {
        throw groundingFailure("Числовое утверждение не совпадает с указанным доказательством.");
      }
    }
    if (!withinDuration(item.time, bundle.durationSeconds)) {
      throw groundingFailure("Ответ модели содержит время за пределами матча.");
    }
    if (item.time !== null) {
      const timedEvidence = knownEvidence.filter((evidence) => evidence.time !== null);
      if (!timedEvidence.some((evidence) => sameTime(item.time!, evidence.time!))) {
        throw groundingFailure("Время в ответе модели не подтверждено указанными доказательствами.");
      }
    }
    if (item.playerSlot !== null) {
      if (playerSlot === null || item.playerSlot !== playerSlot) {
        throw groundingFailure("Ответ модели содержит неподтверждённый слот игрока.");
      }
      if (!knownEvidence.some((evidence) => evidence.playerSlot === item.playerSlot)) {
        throw groundingFailure("Слот игрока в ответе не подтверждён указанными доказательствами.");
      }
    }
  }
  return compileCoachingPresentation(report, bundle);
}
