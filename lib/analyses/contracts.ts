import { z } from "zod";
import { PlayerMatchRequestSchema } from "@/lib/dota/player-identity";

import {
  AnalysisReportV1Schema,
  MATCH_ID_PATTERN,
  PlayerSlotSchema,
  EvidenceBundleV1Schema,
  NormalizedMatchV1Schema,
} from "@/lib/analysis/contracts";

export const ANALYSIS_REPORT_VERSION = "analysis-report.v1" as const;
export const ANALYSIS_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const IDEMPOTENCY_KEY_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,127}$/;

export const AnalysisJobStateSchema = z.enum([
  "queued",
  "running",
  "ready",
  "failed",
  "canceled",
]);
export type AnalysisJobState = z.infer<typeof AnalysisJobStateSchema>;

export const CreateAnalysisRequestSchema = PlayerMatchRequestSchema;
export type CreateAnalysisRequest = z.infer<typeof CreateAnalysisRequestSchema>;

export const AnalysisFailureSchema = z.object({
  code: z.string().regex(/^[A-Z][A-Z0-9_]{2,79}$/),
  message: z.string().trim().min(1).max(512),
  retryable: z.boolean(),
}).strict();

export const PublicAnalysisJobSchema = z.object({
  id: z.string().regex(ANALYSIS_ID_PATTERN),
  matchId: z.string().regex(MATCH_ID_PATTERN),
  playerSlot: PlayerSlotSchema,
  reportVersion: z.literal(ANALYSIS_REPORT_VERSION),
  state: AnalysisJobStateSchema,
  attempt: z.number().int().nonnegative(),
  maxAttempts: z.number().int().positive(),
  failure: AnalysisFailureSchema.nullable(),
  createdAt: z.string().min(1).max(64),
  updatedAt: z.string().min(1).max(64),
}).strict();
export type PublicAnalysisJob = z.infer<typeof PublicAnalysisJobSchema>;

export const AnalysisDetailSchema = z.object({
  job: PublicAnalysisJobSchema,
  report: AnalysisReportV1Schema.nullable(),
  evidenceBundle: EvidenceBundleV1Schema.nullable().optional(),
  match: NormalizedMatchV1Schema.nullable().optional(),
}).strict();
export type AnalysisDetail = z.infer<typeof AnalysisDetailSchema>;

export const AnalysisHistorySchema = z.object({
  jobs: z.array(PublicAnalysisJobSchema).max(50),
  nextCursor: z.string().max(512).nullable(),
}).strict();
export type AnalysisHistory = z.infer<typeof AnalysisHistorySchema>;
