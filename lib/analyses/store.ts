import {
  ANALYSIS_REPORT_VERSION,
  AnalysisDetailSchema,
  AnalysisHistorySchema,
  PublicAnalysisJobSchema,
  type AnalysisDetail,
  type AnalysisHistory,
  type PublicAnalysisJob,
} from "@/lib/analyses/contracts";
import { canonicalJson, canonicalSha256 } from "@/lib/analysis/canonical-json";
import {
  AnalysisReportV1Schema,
  type AnalysisReportV1,
  type EvidenceBundleV1,
  EvidenceBundleV1Schema,
  NormalizedMatchV1Schema,
  type NormalizedMatchV1,
} from "@/lib/analysis/contracts";
import { validateGroundedReport } from "@/lib/analysis/grounding";
import { storageUnavailable } from "@/lib/analyses/errors";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";
import { IdentityRosterSchema } from "@/lib/dota/player-identity";

const DEFAULT_HISTORY_LIMIT = 20;
const MAX_HISTORY_LIMIT = 50;
const LEASE_SECONDS = 90;

const RETRYABLE_FAILURE_CODES = new Set([
  "ANALYSIS_CANCELLED",
  "ANALYSIS_INTERNAL_ERROR",
  "OPENAI_RATE_LIMITED",
  "OPENAI_UNAVAILABLE",
  "OPENDOTA_RATE_LIMITED",
  "OPENDOTA_UNAVAILABLE",
  "STORAGE_UNAVAILABLE",
]);

type JobRow = {
  id: string;
  matchId: string;
  playerSlot: number;
  reportVersion: string;
  state: string;
  attempt: number;
  maxAttempts: number;
  failureCode: string | null;
  failureMessage: string | null;
  createdAt: string;
  updatedAt: string;
  entitlementReservationId?: string | null;
  leaseToken?: string | null;
};

type DetailRow = JobRow & {
  reportPayload: string | null;
  evidencePayload: string | null;
  normalizedPayload: string | null;
};

export type CreateStoredAnalysisInput = {
  userId: string;
  matchId: string;
  playerSlot: number;
  idempotencyKey: string;
};

export type CreateStoredAnalysisResult =
  | { outcome: "created" | "replayed"; job: PublicAnalysisJob }
  | { outcome: "idempotency_conflict" }
  | { outcome: "insufficient_entitlement" }
  | { outcome: "rate_limited" };

export type ClaimedAnalysis = {
  id: string;
  userId: string;
  matchId: string;
  playerSlot: number;
  reportVersion: typeof ANALYSIS_REPORT_VERSION;
  attempt: number;
  maxAttempts: number;
  reservationId: string;
  leaseToken: string;
};

export type ClaimAnalysisResult =
  | { outcome: "claimed"; claim: ClaimedAnalysis }
  | { outcome: "busy"; retryAfterSeconds?: number }
  | { outcome: "not_found" | "ready" | "terminal" };

export type FailAnalysisResult =
  | { outcome: "queued"; retryAfterSeconds: number }
  | { outcome: "failed" | "lease_lost" };

const DEFAULT_RETRY_AFTER_SECONDS = 5;
const MAX_RETRY_AFTER_SECONDS = 60 * 60;

function retryAfterSeconds(value: number | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(1, Math.min(MAX_RETRY_AFTER_SECONDS, Math.ceil(value)))
    : DEFAULT_RETRY_AFTER_SECONDS;
}

function publicJob(row: JobRow): PublicAnalysisJob {
  return PublicAnalysisJobSchema.parse({
    id: row.id,
    matchId: row.matchId,
    playerSlot: row.playerSlot,
    reportVersion: row.reportVersion,
    state: row.state,
    attempt: row.attempt,
    maxAttempts: row.maxAttempts,
    failure: row.failureCode && row.failureMessage
      ? {
          code: row.failureCode,
          message: row.failureMessage,
          retryable: row.state === "queued"
            && row.attempt < row.maxAttempts
            && RETRYABLE_FAILURE_CODES.has(row.failureCode),
        }
      : null,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  });
}

function rowProjection(prefix = "") {
  const column = (name: string) => `${prefix}${name}`;
  return `
    ${column("id")} AS id,
    ${column("match_id")} AS matchId,
    ${column("player_slot")} AS playerSlot,
    ${column("report_version")} AS reportVersion,
    ${column("state")} AS state,
    ${column("attempt")} AS attempt,
    ${column("max_attempts")} AS maxAttempts,
    ${column("failure_code")} AS failureCode,
    ${column("failure_message")} AS failureMessage,
    ${column("created_at")} AS createdAt,
    ${column("updated_at")} AS updatedAt
  `;
}

function encodeCursor(createdAt: string, id: string): string {
  return btoa(JSON.stringify([createdAt, id]));
}

export function decodeAnalysisCursor(cursor: string): [string, string] | null {
  if (!cursor || cursor.length > 512) return null;
  try {
    const decoded: unknown = JSON.parse(atob(cursor));
    if (
      !Array.isArray(decoded)
      || decoded.length !== 2
      || typeof decoded[0] !== "string"
      || decoded[0].length < 1
      || decoded[0].length > 64
      || typeof decoded[1] !== "string"
      || !/^[0-9a-f-]{36}$/i.test(decoded[1])
    ) return null;
    return [decoded[0], decoded[1]];
  } catch {
    return null;
  }
}

function safeFailureMessage(message: string) {
  const normalized = message.trim();
  return (normalized || "Не удалось завершить анализ.").slice(0, 512);
}

export class D1AnalysisStore {
  constructor(private readonly db: D1Database) {}

  private async findByIdempotency(userId: string, idempotencyKey: string) {
    return this.db.prepare(`
      SELECT ${rowProjection() }, request_hash AS requestHash
      FROM analysis_jobs
      WHERE user_id = ?1 AND idempotency_key = ?2
      LIMIT 1
    `).bind(userId, idempotencyKey).first<JobRow & { requestHash: string }>();
  }

  private async findByIdentity(userId: string, matchId: string, playerSlot: number) {
    return this.db.prepare(`
      SELECT ${rowProjection()}
      FROM analysis_jobs
      WHERE user_id = ?1
        AND match_id = ?2
        AND player_slot = ?3
        AND report_version = ?4
        AND state IN ('queued', 'running', 'ready')
      ORDER BY created_at DESC, id DESC
      LIMIT 1
    `).bind(userId, matchId, playerSlot, ANALYSIS_REPORT_VERSION).first<JobRow>();
  }

  async create(input: CreateStoredAnalysisInput): Promise<CreateStoredAnalysisResult> {
    await new D1PlayerBindingStore(this.db).assertTarget(input.userId,input.matchId,input.playerSlot);
    const requestHash = await canonicalSha256({
      matchId: input.matchId,
      playerSlot: input.playerSlot,
      reportVersion: ANALYSIS_REPORT_VERSION,
    });

    try {
      const existingIdempotency = await this.findByIdempotency(input.userId, input.idempotencyKey);
      if (existingIdempotency) {
        return existingIdempotency.requestHash === requestHash
          ? { outcome: "replayed", job: publicJob(existingIdempotency) }
          : { outcome: "idempotency_conflict" };
      }
      const existingIdentity = await this.findByIdentity(input.userId, input.matchId, input.playerSlot);
      if (existingIdentity) return { outcome: "replayed", job: publicJob(existingIdentity) };

      const jobId = crypto.randomUUID();
      const reservationId = crypto.randomUUID();
      const reservationKey = `analysis-job:${jobId}:reserve`;
      await this.db.batch([
        this.db.prepare(`
          INSERT INTO analysis_jobs (
            id, user_id, match_id, player_slot, report_version, state,
            attempt, max_attempts, idempotency_key, request_hash,
            queued_at, created_at, updated_at
          )
          SELECT
            ?1, ?2, ?3, ?4, ?5, 'queued', 0, 3, ?6, ?7,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
          WHERE EXISTS (
            SELECT 1
            FROM entitlement_ledger
            WHERE user_id = ?2
              AND resource = 'analysis'
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            GROUP BY bucket_key
            HAVING SUM(delta) >= 1
          )
          AND EXISTS (SELECT 1 FROM dota_match_targets t JOIN dota_player_profiles p ON p.user_id=t.user_id AND p.account_id=t.account_id WHERE t.user_id=?2 AND t.match_id=?3 AND t.player_slot=?4)
          AND (SELECT COUNT(*) FROM analysis_jobs WHERE user_id=?2 AND state IN ('queued','running')) < 2
          AND NOT EXISTS (SELECT 1 FROM analysis_jobs WHERE user_id=?2 AND match_id=?3 AND player_slot=?4 AND state='failed' AND updated_at>datetime(CURRENT_TIMESTAMP,'-15 minutes'))
          ON CONFLICT DO NOTHING
        `).bind(
          jobId,
          input.userId,
          input.matchId,
          input.playerSlot,
          ANALYSIS_REPORT_VERSION,
          input.idempotencyKey,
          requestHash,
        ),
        this.db.prepare(`
          INSERT INTO entitlement_ledger (
            id, user_id, entry_type, resource, bucket_key, delta,
            idempotency_key, reference_type, reference_id, expires_at
          )
          SELECT
            ?1, ?2, 'reserve', 'analysis', balance.bucket_key, -1,
            ?3, 'analysis_job', ?4, balance.expires_at
          FROM (
            SELECT
              bucket_key,
              MAX(expires_at) AS expires_at,
              MIN(created_at) AS first_created
            FROM entitlement_ledger
            WHERE user_id = ?2
              AND resource = 'analysis'
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            GROUP BY bucket_key
            HAVING SUM(delta) >= 1
            ORDER BY
              CASE WHEN MAX(expires_at) IS NULL THEN 1 ELSE 0 END,
              MAX(expires_at),
              MIN(created_at),
              bucket_key
            LIMIT 1
          ) AS balance
          WHERE EXISTS (
            SELECT 1 FROM analysis_jobs
            WHERE id = ?4
              AND user_id = ?2
              AND idempotency_key = ?5
              AND request_hash = ?6
              AND state = 'queued'
              AND entitlement_reservation_id IS NULL
          )
          ON CONFLICT DO NOTHING
        `).bind(
          reservationId,
          input.userId,
          reservationKey,
          jobId,
          input.idempotencyKey,
          requestHash,
        ),
        this.db.prepare(`
          UPDATE analysis_jobs
          SET entitlement_reservation_id = ?1, updated_at = CURRENT_TIMESTAMP
          WHERE id = ?2
            AND entitlement_reservation_id IS NULL
            AND EXISTS (
              SELECT 1 FROM entitlement_ledger
              WHERE id = ?1
                AND user_id = ?3
                AND entry_type = 'reserve'
                AND resource = 'analysis'
                AND reference_type = 'analysis_job'
                AND reference_id = ?2
            )
        `).bind(reservationId, jobId, input.userId),
        this.db.prepare(`
          DELETE FROM analysis_jobs
          WHERE id = ?1 AND entitlement_reservation_id IS NULL
        `).bind(jobId),
      ]);

      const byIdempotency = await this.findByIdempotency(input.userId, input.idempotencyKey);
      if (byIdempotency) {
        return byIdempotency.requestHash === requestHash
          ? { outcome: byIdempotency.id === jobId ? "created" : "replayed", job: publicJob(byIdempotency) }
          : { outcome: "idempotency_conflict" };
      }
      const byIdentity = await this.findByIdentity(input.userId, input.matchId, input.playerSlot);
      if(byIdentity) return {outcome:"replayed",job:publicJob(byIdentity)};
      const limited=await this.db.prepare(`SELECT 1 AS limited WHERE
        (SELECT COUNT(*) FROM analysis_jobs WHERE user_id=?1 AND state IN ('queued','running'))>=2
        OR EXISTS(SELECT 1 FROM analysis_jobs WHERE user_id=?1 AND match_id=?2 AND player_slot=?3 AND state='failed' AND updated_at>datetime(CURRENT_TIMESTAMP,'-15 minutes'))`).bind(input.userId,input.matchId,input.playerSlot).first();
      return {outcome:limited ? "rate_limited" : "insufficient_entitlement"};
    } catch (error) {
      throw storageUnavailable(error);
    }
  }

  async getOwned(userId: string, analysisId: string): Promise<AnalysisDetail | null> {
    try {
      const row = await this.db.prepare(`
        SELECT ${rowProjection("job.")}, report.report_payload AS reportPayload,
          report.evidence_payload AS evidencePayload, COALESCE(report.normalized_payload,source.normalized_payload) AS normalizedPayload
        FROM analysis_jobs AS job
        LEFT JOIN analysis_reports AS report ON report.job_id = job.id
        LEFT JOIN source_matches AS source ON source.match_id = report.match_id
          AND source.normalizer_version = report.normalizer_version
        WHERE job.id = ?1 AND job.user_id = ?2
        LIMIT 1
      `).bind(analysisId, userId).first<DetailRow>();
      if (!row) return null;
      const target=await new D1PlayerBindingStore(this.db).target(userId,row.matchId);
      if(!target || target.playerSlot!==row.playerSlot) return null;
      let report: AnalysisReportV1 | null = null;
      if (row.reportPayload !== null) {
        report = AnalysisReportV1Schema.parse(JSON.parse(row.reportPayload));
      }
      const evidenceBundle = row.evidencePayload ? EvidenceBundleV1Schema.parse(JSON.parse(row.evidencePayload)) : null;
      let match = row.normalizedPayload ? NormalizedMatchV1Schema.parse(JSON.parse(row.normalizedPayload)) : null;
      if (evidenceBundle && report) {
        if (evidenceBundle.matchId !== row.matchId || await canonicalSha256(evidenceBundle) !== report.evidenceHash) throw new Error("Saved evidence integrity mismatch");
        report = await validateGroundedReport(report,evidenceBundle,{evidenceHash:report.evidenceHash,playerSlot:row.playerSlot});
      }
      if (match && (!evidenceBundle || match.matchId !== row.matchId || await canonicalSha256(match) !== evidenceBundle.normalizedMatchHash)) match = null;
      return AnalysisDetailSchema.parse({ job: publicJob(row), report, evidenceBundle, match });
    } catch (error) {
      throw storageUnavailable(error);
    }
  }

  async getReadyReplay(userId:string,matchId:string):Promise<NormalizedMatchV1|null> {
    const row=await this.db.prepare("SELECT normalized_payload AS payload,identity_payload AS identities FROM replay_uploads WHERE user_id=?1 AND match_id=?2 AND state='ready' ORDER BY updated_at DESC LIMIT 1").bind(userId,matchId).first<{payload:string|null;identities:string|null}>();
    if(!row?.payload)return null;
    const target=await new D1PlayerBindingStore(this.db).target(userId,matchId);
    if(!target||!row.identities)return null;
    const identities=IdentityRosterSchema.parse(JSON.parse(row.identities));
    if(identities.filter(player=>player.accountId===target.accountId).length!==1 || !identities.some(player=>player.accountId===target.accountId&&player.playerSlot===target.playerSlot&&player.heroId===target.heroId))return null;
    const match=NormalizedMatchV1Schema.parse(JSON.parse(row.payload));
    return match.matchId===matchId ? match : null;
  }

  async reconcileOwned(userId:string) {
    const stale=await this.db.prepare(`SELECT id FROM analysis_jobs WHERE user_id=?1
      AND ((state='running' AND attempt>=max_attempts AND lease_expires_at<=CURRENT_TIMESTAMP)
        OR (state IN ('queued','running') AND updated_at<datetime(CURRENT_TIMESTAMP,'-1 day')
          AND (lease_expires_at IS NULL OR lease_expires_at<=CURRENT_TIMESTAMP))) LIMIT 25`).bind(userId).all<{id:string}>();
    for(const {id} of stale.results){await this.releaseExhaustedLease(userId,id);await this.cancelOwned(userId,id);}
  }

  async listOwned(
    userId: string,
    options: { cursor?: [string, string] | null; limit?: number } = {},
  ): Promise<AnalysisHistory> {
    await this.reconcileOwned(userId);
    const limit = Math.min(
      MAX_HISTORY_LIMIT,
      Math.max(1, Math.trunc(options.limit ?? DEFAULT_HISTORY_LIMIT)),
    );
    const cursor = options.cursor ?? null;
    try {
      const statement = cursor
        ? this.db.prepare(`
            SELECT ${rowProjection()}
            FROM analysis_jobs
            WHERE user_id = ?1
              AND (created_at < ?2 OR (created_at = ?2 AND id < ?3))
            ORDER BY created_at DESC, id DESC
            LIMIT ?4
          `).bind(userId, cursor[0], cursor[1], limit + 1)
        : this.db.prepare(`
            SELECT ${rowProjection()}
            FROM analysis_jobs
            WHERE user_id = ?1
            ORDER BY created_at DESC, id DESC
            LIMIT ?2
          `).bind(userId, limit + 1);
      const result = await statement.all<JobRow>();
      const rows = result.results ?? [];
      const page = rows.slice(0, limit);
      const last = page.at(-1);
      return AnalysisHistorySchema.parse({
        jobs: page.map(publicJob),
        nextCursor: rows.length > limit && last
          ? encodeCursor(last.createdAt, last.id)
          : null,
      });
    } catch (error) {
      throw storageUnavailable(error);
    }
  }

  async claimOwned(userId: string, analysisId: string): Promise<ClaimAnalysisResult> {
    const leaseToken = crypto.randomUUID();
    try {
      const results = await this.db.batch([
        this.db.prepare(`
          INSERT INTO analysis_attempts(lease_token,job_id,user_id)
          SELECT ?1,id,user_id FROM analysis_jobs
          WHERE id=?2 AND user_id=?3 AND entitlement_reservation_id IS NOT NULL
            AND attempt < max_attempts
            AND ((state='queued' AND (retry_not_before IS NULL OR retry_not_before<=CURRENT_TIMESTAMP))
              OR (state='running' AND lease_expires_at<=CURRENT_TIMESTAMP))
            AND (SELECT COUNT(*) FROM analysis_attempts WHERE user_id=?3 AND started_at>datetime(CURRENT_TIMESTAMP,'-1 day')) < 9
            AND (SELECT COUNT(*) FROM analysis_attempts WHERE started_at>datetime(CURRENT_TIMESTAMP,'-1 day')) < 100
            AND (SELECT COUNT(*) FROM analysis_jobs WHERE user_id=?3 AND id<>?2 AND state='running' AND lease_expires_at>CURRENT_TIMESTAMP) < 2
        `).bind(leaseToken,analysisId,userId),
        this.db.prepare(`
        UPDATE analysis_jobs
        SET state = 'running',
            attempt = attempt + 1,
            lease_token = ?1,
            lease_expires_at = datetime(CURRENT_TIMESTAMP, ?2),
            retry_not_before = NULL,
            failure_code = NULL,
            failure_message = NULL,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?3
          AND user_id = ?4
          AND EXISTS (SELECT 1 FROM analysis_attempts WHERE lease_token=?1 AND job_id=?3 AND user_id=?4)
          AND entitlement_reservation_id IS NOT NULL
          AND attempt < max_attempts
          AND (
            (
              state = 'queued'
              AND (retry_not_before IS NULL OR retry_not_before <= CURRENT_TIMESTAMP)
            )
            OR (
              state = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= CURRENT_TIMESTAMP
            )
          )
        RETURNING
          id,
          user_id AS userId,
          match_id AS matchId,
          player_slot AS playerSlot,
          report_version AS reportVersion,
          attempt,
          max_attempts AS maxAttempts,
          entitlement_reservation_id AS reservationId
      `).bind(
        leaseToken,
        `+${LEASE_SECONDS} seconds`,
        analysisId,
        userId,
      )]);
      const claimed = results[1].results?.[0] as Omit<ClaimedAnalysis,"leaseToken"> | undefined;
      if (claimed) return { outcome: "claimed", claim: { ...claimed, leaseToken } };

      await this.releaseExhaustedLease(userId, analysisId);
      const current = await this.db.prepare(`
        SELECT
          state,
          CASE
            WHEN state = 'queued'
              AND retry_not_before IS NOT NULL
              AND retry_not_before > CURRENT_TIMESTAMP
              THEN MAX(1, CAST(strftime('%s', retry_not_before) AS INTEGER) - CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER))
            WHEN state = 'running'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at > CURRENT_TIMESTAMP
              THEN MAX(1, CAST(strftime('%s', lease_expires_at) AS INTEGER) - CAST(strftime('%s', CURRENT_TIMESTAMP) AS INTEGER))
            ELSE NULL
          END AS retryAfterSeconds
        FROM analysis_jobs
        WHERE id = ?1 AND user_id = ?2
        LIMIT 1
      `).bind(analysisId, userId).first<{ state: string; retryAfterSeconds: number | null }>();
      if (!current) return { outcome: "not_found" };
      if (current.state === "ready") return { outcome: "ready" };
      if (current.state === "failed" || current.state === "canceled") return { outcome: "terminal" };
      return {
        outcome: "busy",
        ...(current.retryAfterSeconds === null
          ? { retryAfterSeconds: 3600 }
          : { retryAfterSeconds: Math.max(1, Math.min(MAX_RETRY_AFTER_SECONDS, current.retryAfterSeconds)) }),
      };
    } catch (error) {
      throw storageUnavailable(error);
    }
  }

  private async releaseExhaustedLease(userId: string, analysisId: string) {
    const releaseId = crypto.randomUUID();
    const releaseKey = `analysis-job:${analysisId}:exhausted-release`;
    await this.db.batch([
      this.db.prepare(`
        INSERT INTO entitlement_ledger (
          id, user_id, order_id, entry_type, resource, bucket_key, delta,
          idempotency_key, reference_type, reference_id, resolution_of,
          product_code, product_version, expires_at
        )
        SELECT
          ?1, reservation.user_id, reservation.order_id, 'release',
          reservation.resource, reservation.bucket_key, -reservation.delta, ?2,
          reservation.reference_type, reservation.reference_id, reservation.id,
          reservation.product_code, reservation.product_version, reservation.expires_at
        FROM entitlement_ledger AS reservation
        INNER JOIN analysis_jobs AS job
          ON job.entitlement_reservation_id = reservation.id
        WHERE job.id = ?3
          AND job.user_id = ?4
          AND job.state = 'running'
          AND job.attempt >= job.max_attempts
          AND job.lease_expires_at IS NOT NULL
          AND job.lease_expires_at <= CURRENT_TIMESTAMP
          AND reservation.entry_type = 'reserve'
          AND NOT EXISTS (
            SELECT 1 FROM entitlement_ledger WHERE resolution_of = reservation.id
          )
        ON CONFLICT DO NOTHING
      `).bind(releaseId, releaseKey, analysisId, userId),
      this.db.prepare(`
        UPDATE analysis_jobs
        SET state = 'failed',
            lease_token = NULL,
            lease_expires_at = NULL,
            retry_not_before = NULL,
            failure_code = 'ANALYSIS_ATTEMPTS_EXHAUSTED',
            failure_message = 'Последняя попытка была прервана; резерв разбора возвращён.',
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?1
          AND user_id = ?2
          AND state = 'running'
          AND attempt >= max_attempts
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= CURRENT_TIMESTAMP
          AND EXISTS (
            SELECT 1 FROM entitlement_ledger
            WHERE resolution_of = analysis_jobs.entitlement_reservation_id
              AND entry_type = 'release'
          )
      `).bind(analysisId, userId),
    ]);
  }

  async cancelOwned(
    userId: string,
    analysisId: string,
  ): Promise<{ outcome: "canceled" | "unchanged"; detail: AnalysisDetail } | null> {
    const releaseId = crypto.randomUUID();
    const releaseKey = `analysis-job:${analysisId}:cancel-release`;
    try {
      await this.db.batch([
        this.db.prepare(`
          INSERT INTO entitlement_ledger (
            id, user_id, order_id, entry_type, resource, bucket_key, delta,
            idempotency_key, reference_type, reference_id, resolution_of,
            product_code, product_version, expires_at
          )
          SELECT
            ?1, reservation.user_id, reservation.order_id, 'release',
            reservation.resource, reservation.bucket_key, -reservation.delta, ?2,
            reservation.reference_type, reservation.reference_id, reservation.id,
            reservation.product_code, reservation.product_version, reservation.expires_at
          FROM entitlement_ledger AS reservation
          INNER JOIN analysis_jobs AS job
            ON job.entitlement_reservation_id = reservation.id
          WHERE job.id = ?3
            AND job.user_id = ?4
            AND (
              job.state = 'queued'
              OR (
                job.state = 'running'
                AND job.lease_expires_at IS NOT NULL
                AND job.lease_expires_at <= CURRENT_TIMESTAMP
              )
            )
            AND reservation.entry_type = 'reserve'
            AND NOT EXISTS (
              SELECT 1 FROM entitlement_ledger WHERE resolution_of = reservation.id
            )
          ON CONFLICT DO NOTHING
        `).bind(releaseId, releaseKey, analysisId, userId),
        this.db.prepare(`
          UPDATE analysis_jobs
          SET state = 'canceled',
              lease_token = NULL,
              lease_expires_at = NULL,
              retry_not_before = NULL,
              failure_code = NULL,
              failure_message = NULL,
              completed_at = CURRENT_TIMESTAMP,
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ?1
            AND user_id = ?2
            AND (
              state = 'queued'
              OR (
                state = 'running'
                AND lease_expires_at IS NOT NULL
                AND lease_expires_at <= CURRENT_TIMESTAMP
              )
            )
            AND EXISTS (
              SELECT 1 FROM entitlement_ledger
              WHERE resolution_of = analysis_jobs.entitlement_reservation_id
                AND entry_type = 'release'
            )
        `).bind(analysisId, userId),
      ]);
      const detail = await this.getOwned(userId, analysisId);
      if (!detail) return null;
      return {
        outcome: detail.job.state === "canceled" ? "canceled" : "unchanged",
        detail,
      };
    } catch (error) {
      if (error instanceof Error && error.name === "AnalysisRouteError") throw error;
      throw storageUnavailable(error);
    }
  }

  async complete(
    claim: ClaimedAnalysis,
    input: {
      evidenceBundle: EvidenceBundleV1;
      evidenceHash: string;
      report: AnalysisReportV1;
      normalizerVersion: string;
      normalizedMatch?: NormalizedMatchV1;
      model: string;
      promptVersion: string;
    },
  ): Promise<boolean> {
    const reportId = crypto.randomUUID();
    const consumeId = crypto.randomUUID();
    const consumeKey = `reservation:${claim.reservationId}:consume`;
    const evidencePayload = canonicalJson(input.evidenceBundle);
    const reportPayload = canonicalJson(input.report);
    try {
      await this.db.batch([
        this.db.prepare(`
          INSERT INTO entitlement_ledger (
            id, user_id, order_id, entry_type, resource, bucket_key, delta,
            idempotency_key, reference_type, reference_id, resolution_of,
            product_code, product_version, expires_at
          )
          SELECT
            ?1, reservation.user_id, reservation.order_id, 'consume',
            reservation.resource, reservation.bucket_key, 0, ?2,
            reservation.reference_type, reservation.reference_id, reservation.id,
            reservation.product_code, reservation.product_version, reservation.expires_at
          FROM entitlement_ledger AS reservation
          INNER JOIN analysis_jobs AS job
            ON job.entitlement_reservation_id = reservation.id
          WHERE reservation.id = ?3
            AND reservation.entry_type = 'reserve'
            AND job.id = ?4
            AND job.user_id = ?5
            AND job.state = 'running'
            AND job.lease_token = ?6
            AND NOT EXISTS (
              SELECT 1 FROM entitlement_ledger WHERE resolution_of = reservation.id
            )
          ON CONFLICT DO NOTHING
        `).bind(
          consumeId,
          consumeKey,
          claim.reservationId,
          claim.id,
          claim.userId,
          claim.leaseToken,
        ),
        this.db.prepare(`
          INSERT INTO analysis_reports (
            id, job_id, user_id, match_id, player_slot, report_version,
            normalizer_version, evidence_hash, evidence_payload, report_payload,
            model, prompt_version, created_at, normalized_payload
          )
          SELECT
            ?1, job.id, job.user_id, job.match_id, job.player_slot,
            job.report_version, ?2, ?3, ?4, ?5, ?6, ?7, CURRENT_TIMESTAMP, ?11
          FROM analysis_jobs AS job
          WHERE job.id = ?8
            AND job.user_id = ?9
            AND job.state = 'running'
            AND job.lease_token = ?10
            AND EXISTS (
              SELECT 1 FROM entitlement_ledger
              WHERE resolution_of = job.entitlement_reservation_id
                AND entry_type = 'consume'
            )
          ON CONFLICT DO NOTHING
        `).bind(
          reportId,
          input.normalizerVersion,
          input.evidenceHash,
          evidencePayload,
          reportPayload,
          input.model,
          input.promptVersion,
          claim.id,
          claim.userId,
          claim.leaseToken,
          input.normalizedMatch ? canonicalJson(input.normalizedMatch) : null,
        ),
        this.db.prepare(`
          UPDATE analysis_jobs
          SET state = 'ready',
              lease_token = NULL,
              lease_expires_at = NULL,
              retry_not_before = NULL,
              failure_code = NULL,
              failure_message = NULL,
              completed_at = CURRENT_TIMESTAMP,
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ?1
            AND user_id = ?2
            AND state = 'running'
            AND lease_token = ?3
            AND EXISTS (
              SELECT 1 FROM analysis_reports WHERE job_id = ?1
            )
            AND EXISTS (
              SELECT 1 FROM entitlement_ledger
              WHERE resolution_of = analysis_jobs.entitlement_reservation_id
                AND entry_type = 'consume'
            )
        `).bind(claim.id, claim.userId, claim.leaseToken),
      ]);
      const ready = await this.db.prepare(`
        SELECT 1 AS ready FROM analysis_jobs
        WHERE id = ?1 AND user_id = ?2 AND state = 'ready'
      `).bind(claim.id, claim.userId).first<{ ready: number }>();
      return ready?.ready === 1;
    } catch (error) {
      throw storageUnavailable(error);
    }
  }

  async fail(
    claim: ClaimedAnalysis,
    failure: { code: string; message: string; retryable: boolean; retryAfterSeconds?: number },
  ): Promise<FailAnalysisResult> {
    const code = /^[A-Z][A-Z0-9_]{2,79}$/.test(failure.code)
      ? failure.code
      : "ANALYSIS_INTERNAL_ERROR";
    const message = safeFailureMessage(failure.message);
    const shouldRetry = failure.retryable && claim.attempt < claim.maxAttempts;
    try {
      if (shouldRetry) {
        const delay = retryAfterSeconds(failure.retryAfterSeconds);
        const result = await this.db.prepare(`
          UPDATE analysis_jobs
          SET state = 'queued',
              lease_token = NULL,
              lease_expires_at = NULL,
              retry_not_before = datetime(CURRENT_TIMESTAMP, ?3),
              failure_code = ?1,
              failure_message = ?2,
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ?4
            AND user_id = ?5
            AND state = 'running'
            AND lease_token = ?6
        `).bind(
          code,
          message,
          `+${delay} seconds`,
          claim.id,
          claim.userId,
          claim.leaseToken,
        ).run();
        return result.meta.changes === 1
          ? { outcome: "queued", retryAfterSeconds: delay }
          : { outcome: "lease_lost" };
      }

      const releaseId = crypto.randomUUID();
      const releaseKey = `reservation:${claim.reservationId}:release`;
      await this.db.batch([
        this.db.prepare(`
          INSERT INTO entitlement_ledger (
            id, user_id, order_id, entry_type, resource, bucket_key, delta,
            idempotency_key, reference_type, reference_id, resolution_of,
            product_code, product_version, expires_at
          )
          SELECT
            ?1, reservation.user_id, reservation.order_id, 'release',
            reservation.resource, reservation.bucket_key, -reservation.delta, ?2,
            reservation.reference_type, reservation.reference_id, reservation.id,
            reservation.product_code, reservation.product_version, reservation.expires_at
          FROM entitlement_ledger AS reservation
          INNER JOIN analysis_jobs AS job
            ON job.entitlement_reservation_id = reservation.id
          WHERE reservation.id = ?3
            AND reservation.entry_type = 'reserve'
            AND job.id = ?4
            AND job.user_id = ?5
            AND job.state = 'running'
            AND job.lease_token = ?6
            AND NOT EXISTS (
              SELECT 1 FROM entitlement_ledger WHERE resolution_of = reservation.id
            )
          ON CONFLICT DO NOTHING
        `).bind(
          releaseId,
          releaseKey,
          claim.reservationId,
          claim.id,
          claim.userId,
          claim.leaseToken,
        ),
        this.db.prepare(`
          UPDATE analysis_jobs
          SET state = 'failed',
              lease_token = NULL,
              lease_expires_at = NULL,
              retry_not_before = NULL,
              failure_code = ?1,
              failure_message = ?2,
              completed_at = CURRENT_TIMESTAMP,
              updated_at = CURRENT_TIMESTAMP
          WHERE id = ?3
            AND user_id = ?4
            AND state = 'running'
            AND lease_token = ?5
            AND EXISTS (
              SELECT 1 FROM entitlement_ledger
              WHERE resolution_of = analysis_jobs.entitlement_reservation_id
                AND entry_type = 'release'
            )
        `).bind(code, message, claim.id, claim.userId, claim.leaseToken),
      ]);
      const terminal = await this.db.prepare(`
        SELECT state FROM analysis_jobs WHERE id = ?1 AND user_id = ?2
      `).bind(claim.id, claim.userId).first<{ state: string }>();
      return terminal?.state === "failed"
        ? { outcome: "failed" }
        : { outcome: "lease_lost" };
    } catch (error) {
      throw storageUnavailable(error);
    }
  }
}
