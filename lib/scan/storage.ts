import {
  NORMALIZED_MATCH_SCHEMA_VERSION,
  NormalizedMatchV1Schema,
  type NormalizedMatchV1,
} from "@/lib/analysis/contracts";
import { canonicalJson, canonicalSha256 } from "@/lib/analysis/canonical-json";
import { scanUnavailable } from "@/lib/scan/errors";

export const SCAN_NORMALIZER_VERSION = `${NORMALIZED_MATCH_SCHEMA_VERSION}.opendota-3-fight-players` as const;
export const SCAN_RATE_LIMIT_SCOPE = "anonymous_scan" as const;
export const SCAN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60;
export const SCAN_RATE_LIMIT_MAX_REQUESTS = 12;

const MAX_CACHED_PAYLOAD_CHARS = 2 * 1024 * 1024;

export interface ScanMatchCache {
  get(matchId: string): Promise<NormalizedMatchV1 | null>;
  put(match: NormalizedMatchV1): Promise<void>;
}

export type ScanRateLimitResult = {
  allowed: boolean;
  count: number;
  limit: number;
  retryAfterSeconds: number;
};

export interface ScanRateLimiter {
  take(keyHash: string, nowMs: number): Promise<ScanRateLimitResult>;
}

export function scanRateWindowStart(
  nowMs: number,
  windowSeconds = SCAN_RATE_LIMIT_WINDOW_SECONDS,
): number {
  if (!Number.isFinite(nowMs)) throw new TypeError("nowMs must be finite");
  if (!Number.isSafeInteger(windowSeconds) || windowSeconds < 1) {
    throw new RangeError("windowSeconds must be positive");
  }
  return Math.floor(Math.floor(nowMs / 1000) / windowSeconds) * windowSeconds;
}

export class D1ScanMatchCache implements ScanMatchCache {
  constructor(private readonly db: D1Database) {}

  async get(matchId: string): Promise<NormalizedMatchV1 | null> {
    let row: { normalizedPayload: string | null; payloadHash: string | null } | null;
    try {
      row = await this.db.prepare(`
        SELECT normalized_payload AS normalizedPayload, payload_hash AS payloadHash
        FROM source_matches
        WHERE match_id = ?1
          AND normalizer_version = ?2
          AND source_provider = 'opendota'
          AND source_status = 'normalized'
        LIMIT 1
      `).bind(matchId, SCAN_NORMALIZER_VERSION).first();
    } catch (error) {
      throw scanUnavailable(error);
    }

    if (!row?.normalizedPayload || !row.payloadHash) return null;
    if (row.normalizedPayload.length > MAX_CACHED_PAYLOAD_CHARS) return null;
    try {
      const parsed = NormalizedMatchV1Schema.parse(JSON.parse(row.normalizedPayload));
      if (parsed.matchId !== matchId) return null;
      const hash = await canonicalSha256(parsed);
      return hash === row.payloadHash ? parsed : null;
    } catch {
      return null;
    }
  }

  async put(matchInput: NormalizedMatchV1): Promise<void> {
    const match = NormalizedMatchV1Schema.parse(matchInput);
    const normalizedPayload = canonicalJson(match);
    const payloadHash = await canonicalSha256(match);
    try {
      const result = await this.db.prepare(`
        INSERT INTO source_matches (
          id, match_id, normalizer_version, source_provider, source_status,
          parser_version, normalized_payload, payload_hash,
          fetched_at, normalized_at, last_checked_at, created_at, updated_at
        ) VALUES (
          ?1, ?2, ?3, 'opendota', 'normalized', ?4, ?5, ?6,
          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT(match_id, normalizer_version) DO UPDATE SET
          source_provider = 'opendota',
          source_status = 'normalized',
          parser_version = excluded.parser_version,
          normalized_payload = excluded.normalized_payload,
          payload_hash = excluded.payload_hash,
          fetched_at = CURRENT_TIMESTAMP,
          normalized_at = CURRENT_TIMESTAMP,
          last_checked_at = CURRENT_TIMESTAMP,
          updated_at = CURRENT_TIMESTAMP
      `).bind(
        crypto.randomUUID(),
        match.matchId,
        SCAN_NORMALIZER_VERSION,
        match.parserVersion === null ? null : String(match.parserVersion),
        normalizedPayload,
        payloadHash,
      ).run();
      if (!result.success) throw new Error("D1 did not persist the normalized match");
    } catch (error) {
      throw scanUnavailable(error);
    }
  }
}

export class D1FixedWindowRateLimiter implements ScanRateLimiter {
  constructor(
    private readonly db: D1Database,
    private readonly limit = SCAN_RATE_LIMIT_MAX_REQUESTS,
    private readonly windowSeconds = SCAN_RATE_LIMIT_WINDOW_SECONDS,
  ) {
    if (!Number.isSafeInteger(limit) || limit < 1) throw new RangeError("limit must be positive");
    if (!Number.isSafeInteger(windowSeconds) || windowSeconds < 1) throw new RangeError("windowSeconds must be positive");
  }

  async take(keyHash: string, nowMs: number): Promise<ScanRateLimitResult> {
    if (!/^[a-f0-9]{64}$/.test(keyHash) || !Number.isFinite(nowMs)) throw new TypeError("invalid rate-limit input");
    const nowSeconds = Math.floor(nowMs / 1000);
    const windowStart = scanRateWindowStart(nowMs, this.windowSeconds);
    const expiresAt = windowStart + this.windowSeconds;

    let row: { count: number } | null;
    try {
      row = await this.db.prepare(`
        INSERT INTO rate_limit_buckets (
          id, scope, key_hash, window_start, count, expires_at, created_at, updated_at
        ) VALUES (?1, ?2, ?3, ?4, 1, ?5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(scope, key_hash, window_start) DO UPDATE SET
          count = rate_limit_buckets.count + 1,
          expires_at = excluded.expires_at,
          updated_at = CURRENT_TIMESTAMP
        RETURNING count
      `).bind(
        crypto.randomUUID(),
        SCAN_RATE_LIMIT_SCOPE,
        keyHash,
        windowStart,
        expiresAt,
      ).first();
    } catch (error) {
      throw scanUnavailable(error);
    }
    if (!row || !Number.isSafeInteger(row.count) || row.count < 1) {
      throw scanUnavailable();
    }

    return {
      allowed: row.count <= this.limit,
      count: row.count,
      limit: this.limit,
      retryAfterSeconds: Math.max(1, expiresAt - nowSeconds),
    };
  }
}
