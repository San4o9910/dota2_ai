import { sql } from "drizzle-orm";
import {
  check,
  index,
  integer,
  sqliteTable,
  text,
  uniqueIndex,
  primaryKey,
  type AnySQLiteColumn,
} from "drizzle-orm/sqlite-core";

export const users = sqliteTable("users", {
  id: text("id").primaryKey(),
  displayName: text("display_name").notNull(),
  status: text("status").notNull().default("active"),
  deletedAt: text("deleted_at"),
  planCode: text("plan_code").notNull().default("free_trial"),
  // Legacy opening-balance fields retained for a non-destructive migration.
  // Account reads and every new mutation use entitlement_ledger instead.
  subscriptionAnalysisCredits: integer("subscription_analysis_credits").notNull().default(0),
  subscriptionCoachQuestionsRemaining: integer("subscription_coach_questions_remaining").notNull().default(0),
  analysisCredits: integer("analysis_credits").notNull().default(1),
  coachQuestionsRemaining: integer("coach_questions_remaining").notNull().default(5),
  planExpiresAt: text("plan_expires_at"),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const authIdentities = sqliteTable(
  "auth_identities",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: text("provider").notNull(),
    providerSubject: text("provider_subject").notNull(),
    email: text("email").notNull(),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    lastSeenAt: text("last_seen_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("auth_provider_subject_unique").on(
      table.provider,
      table.providerSubject,
    ),
  ],
);

// A selected coaching identity, not a claim of verified Steam ownership.
export const dotaPlayerProfiles = sqliteTable("dota_player_profiles", {
  userId: text("user_id").primaryKey().references(() => users.id, { onDelete: "restrict" }),
  accountId: integer("account_id").notNull(),
  nickname: text("nickname").notNull(),
  sourceMatchId: text("source_match_id").notNull(),
  createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, table => [check("dota_profile_account_valid",sql`${table.accountId} BETWEEN 1 AND 4294967294`)]);

export const dotaMatchTargets = sqliteTable("dota_match_targets", {
  userId: text("user_id").notNull().references(() => dotaPlayerProfiles.userId, { onDelete: "restrict" }),
  matchId: text("match_id").notNull(),
  accountId: integer("account_id").notNull(),
  playerSlot: integer("player_slot").notNull(),
  heroId: integer("hero_id").notNull(),
}, table => [primaryKey({columns:[table.userId,table.matchId]}),
  check("dota_target_slot_valid",sql`${table.playerSlot} IN (0,1,2,3,4,128,129,130,131,132)`)]);

/**
 * Durable payment order. The physical name stays `orders` so the first
 * production migration can preserve rows created by the original scaffold.
 * Financial rows never cascade when a user is removed.
 */
export const billingOrders = sqliteTable(
  "orders",
  {
    id: text("id").primaryKey(),
    userId: text("user_id").references(() => users.id, { onDelete: "set null" }),
    productCode: text("product_code").notNull(),
    productVersion: text("product_version").notNull().default("legacy-v0"),
    checkoutAttemptId: text("checkout_attempt_id").notNull().unique(),
    requestHash: text("request_hash"),
    providerIdempotencyKey: text("provider_idempotency_key").unique(),
    matchId: text("match_id"),
    amountKopecks: integer("amount_kopecks").notNull(),
    currency: text("currency").notNull().default("RUB"),
    grantAnalyses: integer("grant_analyses").notNull().default(0),
    grantCoachQuestions: integer("grant_coach_questions").notNull().default(0),
    durationDays: integer("duration_days"),
    environment: text("environment").notNull().default("unknown"),
    paymentMode: text("payment_mode").notNull().default("unknown"),
    provider: text("provider").notNull().default("yookassa"),
    providerShopId: text("provider_shop_id"),
    providerTest: integer("provider_test", { mode: "boolean" }),
    paymentStatus: text("status").notNull().default("created"),
    fulfillmentStatus: text("fulfillment_status").notNull().default("not_granted"),
    refundStatus: text("refund_status").notNull().default("none"),
    yookassaPaymentId: text("yookassa_payment_id").unique(),
    creditedAt: text("credited_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("orders_user_created_idx").on(table.userId, table.createdAt),
    index("orders_payment_status_idx").on(table.paymentStatus, table.updatedAt),
    uniqueIndex("orders_one_unresolved_coach_per_user")
      .on(table.userId)
      .where(sql`
        product_code = 'coach_30_days'
        AND (
          status IN ('created', 'pending', 'waiting_for_capture')
          OR (
            status = 'succeeded'
            AND (credited_at IS NULL OR fulfillment_status <> 'granted')
          )
        )
      `),
    check("orders_amount_positive", sql`${table.amountKopecks} > 0`),
    check("orders_currency_rub", sql`${table.currency} = 'RUB'`),
    check(
      "orders_payment_mode_valid",
      sql`${table.paymentMode} IN ('unknown', 'test', 'live')`,
    ),
    check(
      "orders_provider_test_valid",
      sql`${table.providerTest} IS NULL OR ${table.providerTest} IN (0, 1)`,
    ),
  ],
);

// Compatibility for current route imports while billingOrders is adopted.
export const orders = billingOrders;

export const sourceMatches = sqliteTable(
  "source_matches",
  {
    id: text("id").primaryKey(),
    matchId: text("match_id").notNull(),
    normalizerVersion: text("normalizer_version").notNull(),
    sourceProvider: text("source_provider").notNull().default("opendota"),
    sourceStatus: text("source_status").notNull().default("pending"),
    parserVersion: text("parser_version"),
    normalizedPayload: text("normalized_payload"),
    payloadHash: text("payload_hash"),
    fetchedAt: text("fetched_at"),
    normalizedAt: text("normalized_at"),
    lastCheckedAt: text("last_checked_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("source_matches_match_normalizer_unique").on(
      table.matchId,
      table.normalizerVersion,
    ),
    index("source_matches_status_checked_idx").on(
      table.sourceStatus,
      table.lastCheckedAt,
    ),
    check(
      "source_matches_status_valid",
      sql`${table.sourceStatus} IN ('pending', 'fetched', 'normalized', 'unavailable', 'failed')`,
    ),
  ],
);

export const analysisJobs = sqliteTable(
  "analysis_jobs",
  {
    id: text("id").primaryKey(),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    sourceMatchId: text("source_match_id").references(() => sourceMatches.id, {
      onDelete: "restrict",
    }),
    matchId: text("match_id").notNull(),
    playerSlot: integer("player_slot").notNull(),
    reportVersion: text("report_version").notNull(),
    state: text("state").notNull().default("queued"),
    attempt: integer("attempt").notNull().default(0),
    maxAttempts: integer("max_attempts").notNull().default(3),
    leaseToken: text("lease_token"),
    leaseExpiresAt: text("lease_expires_at"),
    idempotencyKey: text("idempotency_key").notNull(),
    requestHash: text("request_hash").notNull(),
    entitlementReservationId: text("entitlement_reservation_id"),
    failureCode: text("failure_code"),
    failureMessage: text("failure_message"),
    retryNotBefore: text("retry_not_before"),
    queuedAt: text("queued_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    startedAt: text("started_at"),
    completedAt: text("completed_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("analysis_jobs_user_idempotency_unique").on(
      table.userId,
      table.idempotencyKey,
    ),
    uniqueIndex("analysis_jobs_active_report_identity_unique")
      .on(
        table.userId,
        table.matchId,
        table.playerSlot,
        table.reportVersion,
      )
      .where(sql`${table.state} IN ('queued', 'running', 'ready')`),
    index("analysis_jobs_state_lease_idx").on(table.state, table.leaseExpiresAt),
    index("analysis_jobs_user_created_idx").on(table.userId, table.createdAt),
    check(
      "analysis_jobs_player_slot_valid",
      sql`(${table.playerSlot} BETWEEN 0 AND 4) OR (${table.playerSlot} BETWEEN 128 AND 132)`,
    ),
    check("analysis_jobs_attempt_valid", sql`${table.attempt} >= 0 AND ${table.attempt} <= ${table.maxAttempts}`),
    check(
      "analysis_jobs_state_valid",
      sql`${table.state} IN ('queued', 'running', 'ready', 'failed', 'canceled')`,
    ),
  ],
);

export const analysisReports = sqliteTable(
  "analysis_reports",
  {
    id: text("id").primaryKey(),
    jobId: text("job_id")
      .notNull()
      .unique()
      .references(() => analysisJobs.id, { onDelete: "restrict" }),
    userId: text("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "restrict" }),
    matchId: text("match_id").notNull(),
    playerSlot: integer("player_slot").notNull(),
    reportVersion: text("report_version").notNull(),
    normalizerVersion: text("normalizer_version").notNull(),
    evidenceHash: text("evidence_hash").notNull(),
    evidencePayload: text("evidence_payload").notNull(),
    reportPayload: text("report_payload").notNull(),
    normalizedPayload: text("normalized_payload"),
    model: text("model"),
    promptVersion: text("prompt_version"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("analysis_reports_user_created_idx").on(table.userId, table.createdAt),
    uniqueIndex("analysis_reports_identity_unique").on(
      table.userId,
      table.matchId,
      table.playerSlot,
      table.reportVersion,
    ),
  ],
);

export const entitlementLedger = sqliteTable(
  "entitlement_ledger",
  {
    id: text("id").primaryKey(),
    userId: text("user_id").references(() => users.id, { onDelete: "set null" }),
    orderId: text("order_id").references(() => billingOrders.id, { onDelete: "restrict" }),
    entryType: text("entry_type").notNull(),
    resource: text("resource").notNull(),
    bucketKey: text("bucket_key").notNull(),
    delta: integer("delta").notNull(),
    idempotencyKey: text("idempotency_key").notNull().unique(),
    referenceType: text("reference_type").notNull(),
    referenceId: text("reference_id").notNull(),
    resolutionOf: text("resolution_of").references(
      (): AnySQLiteColumn => entitlementLedger.id,
      { onDelete: "restrict" },
    ),
    productCode: text("product_code"),
    productVersion: text("product_version"),
    expiresAt: text("expires_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("entitlement_ledger_user_resource_idx").on(
      table.userId,
      table.resource,
      table.bucketKey,
      table.createdAt,
    ),
    uniqueIndex("entitlement_ledger_one_resolution")
      .on(table.resolutionOf)
      .where(sql`resolution_of IS NOT NULL`),
    uniqueIndex("entitlement_ledger_one_grant_per_bucket")
      .on(table.userId, table.resource, table.bucketKey)
      .where(sql`entry_type = 'grant'`),
    check(
      "entitlement_ledger_entry_type_valid",
      sql`${table.entryType} IN ('grant', 'reserve', 'consume', 'release', 'revoke', 'expire')`,
    ),
    check(
      "entitlement_ledger_resource_valid",
      sql`${table.resource} IN ('analysis', 'coach_question')`,
    ),
    check(
      "entitlement_ledger_delta_valid",
      sql`(${table.entryType} = 'grant' AND ${table.delta} > 0)
        OR (${table.entryType} = 'reserve' AND ${table.delta} < 0)
        OR (${table.entryType} = 'consume' AND ${table.delta} = 0)
        OR (${table.entryType} = 'release' AND ${table.delta} > 0)
        OR (${table.entryType} IN ('revoke', 'expire') AND ${table.delta} < 0)`,
    ),
    check(
      "entitlement_ledger_resolution_shape",
      sql`(${table.entryType} IN ('consume', 'release') AND ${table.resolutionOf} IS NOT NULL)
        OR (${table.entryType} NOT IN ('consume', 'release') AND ${table.resolutionOf} IS NULL)`,
    ),
  ],
);

export const providerEvents = sqliteTable(
  "provider_events",
  {
    id: text("id").primaryKey(),
    orderId: text("order_id").references(() => billingOrders.id, { onDelete: "restrict" }),
    provider: text("provider").notNull(),
    eventType: text("event_type").notNull(),
    providerPaymentId: text("provider_payment_id").notNull(),
    payloadHash: text("payload_hash").notNull(),
    paymentMode: text("payment_mode").notNull(),
    providerTest: integer("provider_test", { mode: "boolean" }),
    receivedAt: text("received_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("provider_events_transition_unique").on(
      table.provider,
      table.eventType,
      table.providerPaymentId,
    ),
    index("provider_events_payment_idx").on(table.providerPaymentId, table.receivedAt),
    check(
      "provider_events_payment_mode_valid",
      sql`${table.paymentMode} IN ('test', 'live')`,
    ),
  ],
);

export const refunds = sqliteTable(
  "refunds",
  {
    id: text("id").primaryKey(),
    orderId: text("order_id")
      .notNull()
      .references(() => billingOrders.id, { onDelete: "restrict" }),
    provider: text("provider").notNull().default("yookassa"),
    providerRefundId: text("provider_refund_id").unique(),
    amountKopecks: integer("amount_kopecks").notNull(),
    currency: text("currency").notNull().default("RUB"),
    paymentMode: text("payment_mode").notNull(),
    providerTest: integer("provider_test", { mode: "boolean" }),
    status: text("status").notNull().default("pending"),
    reason: text("reason"),
    requestedAt: text("requested_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    settledAt: text("settled_at"),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("refunds_order_created_idx").on(table.orderId, table.createdAt),
    check("refunds_amount_positive", sql`${table.amountKopecks} > 0`),
    check("refunds_currency_rub", sql`${table.currency} = 'RUB'`),
    check("refunds_payment_mode_valid", sql`${table.paymentMode} IN ('test', 'live')`),
    check(
      "refunds_status_valid",
      sql`${table.status} IN ('pending', 'succeeded', 'canceled', 'failed')`,
    ),
  ],
);

/** Durable fixed-window counters. keyHash is a server-keyed digest; raw IPs or
 * other direct identifiers must never be stored in this table. */
export const rateLimitBuckets = sqliteTable(
  "rate_limit_buckets",
  {
    id: text("id").primaryKey(),
    scope: text("scope").notNull(),
    keyHash: text("key_hash").notNull(),
    windowStart: integer("window_start").notNull(),
    count: integer("count").notNull().default(1),
    expiresAt: integer("expires_at").notNull(),
    createdAt: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    uniqueIndex("rate_limit_buckets_window_unique").on(
      table.scope,
      table.keyHash,
      table.windowStart,
    ),
    index("rate_limit_buckets_cleanup_idx").on(table.expiresAt),
    check("rate_limit_buckets_count_positive", sql`${table.count} > 0`),
    check("rate_limit_buckets_window_valid", sql`${table.expiresAt} > ${table.windowStart}`),
  ],
);


export const analysisAttempts = sqliteTable("analysis_attempts", {
  leaseToken:text("lease_token").primaryKey(),
  jobId:text("job_id").notNull().references(()=>analysisJobs.id),
  userId:text("user_id").notNull().references(()=>users.id),
  startedAt:text("started_at").notNull().default(sql`CURRENT_TIMESTAMP`),
},t=>[index("analysis_attempts_user_time_idx").on(t.userId,t.startedAt),index("analysis_attempts_time_idx").on(t.startedAt)]);

export const trainingProgress = sqliteTable("training_progress", {
  id:text("id").primaryKey(),userId:text("user_id").notNull().references(()=>users.id,{onDelete:"cascade"}),
  contextId:text("context_id").notNull(),taskId:text("task_id").notNull(),completed:integer("completed",{mode:"boolean"}).notNull().default(false),
  updatedAt:text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
},t=>[uniqueIndex("training_progress_owner_task_idx").on(t.userId,t.contextId,t.taskId),check("training_progress_completed_valid",sql`${t.completed} IN (0,1)`)]);

export const coachExchanges = sqliteTable("coach_exchanges", {
  id:text("id").primaryKey(),userId:text("user_id").notNull().references(()=>users.id,{onDelete:"cascade"}),
  jobId:text("job_id").notNull().references(()=>analysisJobs.id),requestHash:text("request_hash"),question:text("question").notNull(),answer:text("answer").notNull(),
  createdAt:text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
},t=>[index("coach_exchanges_owner_time_idx").on(t.userId,t.createdAt),index("coach_exchanges_job_time_idx").on(t.jobId,t.createdAt)]);

export const replayUploads = sqliteTable("replay_uploads", {
  id:text("id").primaryKey(),userId:text("user_id").notNull().references(()=>users.id),
  completionToken:text("completion_token"),uploadId:text("upload_id"),normalizedPayload:text("normalized_payload"),identityPayload:text("identity_payload"),leaseToken:text("lease_token"),leaseExpiresAt:text("lease_expires_at"),attempt:integer("attempt").notNull().default(0),
  filename:text("filename").notNull(),objectKey:text("object_key").notNull(),sizeBytes:integer("size_bytes").notNull(),
  state:text("state").notNull().default("uploading"),failureCode:text("failure_code"),matchId:text("match_id"),
  createdAt:text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),updatedAt:text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
},t=>[index("replay_uploads_owner_time_idx").on(t.userId,t.createdAt),index("replay_uploads_state_time_idx").on(t.state,t.createdAt),check("replay_uploads_state_valid",sql`${t.state} IN ('uploading','uploaded','processing','ready','failed','deleted')`)]);

export const replayUploadParts=sqliteTable("replay_upload_parts",{
 id:text("id").primaryKey(),replayId:text("replay_id").notNull().references(()=>replayUploads.id),
 partNumber:integer("part_number").notNull(),etag:text("etag").notNull(),sizeBytes:integer("size_bytes").notNull(),
},t=>[uniqueIndex("replay_parts_number_idx").on(t.replayId,t.partNumber)]);
