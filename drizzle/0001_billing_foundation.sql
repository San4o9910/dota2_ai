-- Rebuild the legacy order table before creating new foreign keys that point
-- to it. This avoids relying on PRAGMA foreign_keys=OFF, which D1 migration
-- runners may reject or ignore inside a transaction.
ALTER TABLE `users` ADD `deleted_at` text;--> statement-breakpoint
CREATE TABLE `__new_orders` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text,
	`product_code` text NOT NULL,
	`product_version` text DEFAULT 'legacy-v0' NOT NULL,
	`checkout_attempt_id` text NOT NULL,
	`request_hash` text,
	`provider_idempotency_key` text,
	`match_id` text,
	`amount_kopecks` integer NOT NULL,
	`currency` text DEFAULT 'RUB' NOT NULL,
	`grant_analyses` integer DEFAULT 0 NOT NULL,
	`grant_coach_questions` integer DEFAULT 0 NOT NULL,
	`duration_days` integer,
	`environment` text DEFAULT 'unknown' NOT NULL,
	`payment_mode` text DEFAULT 'unknown' NOT NULL,
	`provider` text DEFAULT 'yookassa' NOT NULL,
	`provider_shop_id` text,
	`provider_test` integer,
	`status` text DEFAULT 'created' NOT NULL,
	`fulfillment_status` text DEFAULT 'not_granted' NOT NULL,
	`refund_status` text DEFAULT 'none' NOT NULL,
	`yookassa_payment_id` text,
	`credited_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE set null,
	CONSTRAINT "orders_amount_positive" CHECK("__new_orders"."amount_kopecks" > 0),
	CONSTRAINT "orders_currency_rub" CHECK("__new_orders"."currency" = 'RUB'),
	CONSTRAINT "orders_payment_mode_valid" CHECK("__new_orders"."payment_mode" IN ('unknown', 'test', 'live')),
	CONSTRAINT "orders_provider_test_valid" CHECK("__new_orders"."provider_test" IS NULL OR "__new_orders"."provider_test" IN (0, 1))
);--> statement-breakpoint
-- Existing rows predate environment and product snapshots. Preserve them, but
-- quarantine them as `unknown` so settlement requires an explicit reconciliation
-- instead of guessing whether an old provider payment was test or live.
INSERT INTO `__new_orders`(
	"id", "user_id", "product_code", "product_version", "checkout_attempt_id",
	"request_hash", "provider_idempotency_key", "match_id", "amount_kopecks",
	"currency", "grant_analyses", "grant_coach_questions", "duration_days",
	"environment", "payment_mode", "provider", "provider_shop_id", "provider_test",
	"status", "fulfillment_status", "refund_status", "yookassa_payment_id",
	"credited_at", "created_at", "updated_at"
)
SELECT
	"id", "user_id", "product_code", 'legacy-v0', "checkout_attempt_id",
	NULL, "id", "match_id", "amount_kopecks", 'RUB',
	CASE "product_code" WHEN 'single_analysis' THEN 1 WHEN 'coach_30_days' THEN 8 ELSE 0 END,
	CASE "product_code" WHEN 'single_analysis' THEN 10 WHEN 'coach_30_days' THEN 40 ELSE 0 END,
	CASE "product_code" WHEN 'coach_30_days' THEN 30 ELSE NULL END,
	'unknown', 'unknown', 'yookassa', NULL, NULL,
	"status", CASE WHEN "credited_at" IS NULL THEN 'not_granted' ELSE 'granted' END,
	'none', "yookassa_payment_id", "credited_at", "created_at", "updated_at"
FROM `orders`;--> statement-breakpoint
DROP TABLE `orders`;--> statement-breakpoint
ALTER TABLE `__new_orders` RENAME TO `orders`;--> statement-breakpoint
CREATE UNIQUE INDEX `orders_checkout_attempt_id_unique` ON `orders` (`checkout_attempt_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `orders_provider_idempotency_key_unique` ON `orders` (`provider_idempotency_key`);--> statement-breakpoint
CREATE UNIQUE INDEX `orders_yookassa_payment_id_unique` ON `orders` (`yookassa_payment_id`);--> statement-breakpoint
CREATE INDEX `orders_user_created_idx` ON `orders` (`user_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `orders_payment_status_idx` ON `orders` (`status`,`updated_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `orders_one_open_coach_per_user` ON `orders` (`user_id`) WHERE
        product_code = 'coach_30_days'
        AND status IN ('created', 'pending', 'waiting_for_capture')
      ;--> statement-breakpoint
CREATE TABLE `analysis_jobs` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`source_match_id` text,
	`match_id` text NOT NULL,
	`player_slot` integer NOT NULL,
	`report_version` text NOT NULL,
	`state` text DEFAULT 'queued' NOT NULL,
	`attempt` integer DEFAULT 0 NOT NULL,
	`max_attempts` integer DEFAULT 3 NOT NULL,
	`lease_token` text,
	`lease_expires_at` text,
	`idempotency_key` text NOT NULL,
	`request_hash` text NOT NULL,
	`entitlement_reservation_id` text,
	`failure_code` text,
	`failure_message` text,
	`queued_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`started_at` text,
	`completed_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE restrict,
	FOREIGN KEY (`source_match_id`) REFERENCES `source_matches`(`id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "analysis_jobs_player_slot_valid" CHECK(("analysis_jobs"."player_slot" BETWEEN 0 AND 4) OR ("analysis_jobs"."player_slot" BETWEEN 128 AND 132)),
	CONSTRAINT "analysis_jobs_attempt_valid" CHECK("analysis_jobs"."attempt" >= 0 AND "analysis_jobs"."attempt" <= "analysis_jobs"."max_attempts"),
	CONSTRAINT "analysis_jobs_state_valid" CHECK("analysis_jobs"."state" IN ('queued', 'running', 'ready', 'failed', 'canceled'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_jobs_user_idempotency_unique` ON `analysis_jobs` (`user_id`,`idempotency_key`);--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_jobs_report_identity_unique` ON `analysis_jobs` (`user_id`,`match_id`,`player_slot`,`report_version`);--> statement-breakpoint
CREATE INDEX `analysis_jobs_state_lease_idx` ON `analysis_jobs` (`state`,`lease_expires_at`);--> statement-breakpoint
CREATE INDEX `analysis_jobs_user_created_idx` ON `analysis_jobs` (`user_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `analysis_reports` (
	`id` text PRIMARY KEY NOT NULL,
	`job_id` text NOT NULL,
	`user_id` text NOT NULL,
	`match_id` text NOT NULL,
	`player_slot` integer NOT NULL,
	`report_version` text NOT NULL,
	`normalizer_version` text NOT NULL,
	`evidence_hash` text NOT NULL,
	`evidence_payload` text NOT NULL,
	`report_payload` text NOT NULL,
	`model` text,
	`prompt_version` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`job_id`) REFERENCES `analysis_jobs`(`id`) ON UPDATE no action ON DELETE restrict,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE restrict
);
--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_reports_job_id_unique` ON `analysis_reports` (`job_id`);--> statement-breakpoint
CREATE INDEX `analysis_reports_user_created_idx` ON `analysis_reports` (`user_id`,`created_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_reports_identity_unique` ON `analysis_reports` (`user_id`,`match_id`,`player_slot`,`report_version`);--> statement-breakpoint
CREATE TABLE `entitlement_ledger` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text,
	`order_id` text,
	`entry_type` text NOT NULL,
	`resource` text NOT NULL,
	`bucket_key` text NOT NULL,
	`delta` integer NOT NULL,
	`idempotency_key` text NOT NULL,
	`reference_type` text NOT NULL,
	`reference_id` text NOT NULL,
	`resolution_of` text,
	`product_code` text,
	`product_version` text,
	`expires_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON UPDATE no action ON DELETE restrict,
	FOREIGN KEY (`resolution_of`) REFERENCES `entitlement_ledger`(`id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "entitlement_ledger_entry_type_valid" CHECK("entitlement_ledger"."entry_type" IN ('grant', 'reserve', 'consume', 'release', 'revoke', 'expire')),
	CONSTRAINT "entitlement_ledger_resource_valid" CHECK("entitlement_ledger"."resource" IN ('analysis', 'coach_question')),
	CONSTRAINT "entitlement_ledger_delta_valid" CHECK(("entitlement_ledger"."entry_type" = 'grant' AND "entitlement_ledger"."delta" > 0)
        OR ("entitlement_ledger"."entry_type" = 'reserve' AND "entitlement_ledger"."delta" < 0)
        OR ("entitlement_ledger"."entry_type" = 'consume' AND "entitlement_ledger"."delta" = 0)
        OR ("entitlement_ledger"."entry_type" = 'release' AND "entitlement_ledger"."delta" > 0)
	        OR ("entitlement_ledger"."entry_type" IN ('revoke', 'expire') AND "entitlement_ledger"."delta" < 0)),
	CONSTRAINT "entitlement_ledger_resolution_shape" CHECK(("entitlement_ledger"."entry_type" IN ('consume', 'release') AND "entitlement_ledger"."resolution_of" IS NOT NULL)
	        OR ("entitlement_ledger"."entry_type" NOT IN ('consume', 'release') AND "entitlement_ledger"."resolution_of" IS NULL))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `entitlement_ledger_idempotency_key_unique` ON `entitlement_ledger` (`idempotency_key`);--> statement-breakpoint
CREATE INDEX `entitlement_ledger_user_resource_idx` ON `entitlement_ledger` (`user_id`,`resource`,`bucket_key`,`created_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `entitlement_ledger_one_resolution` ON `entitlement_ledger` (`resolution_of`) WHERE resolution_of IS NOT NULL;--> statement-breakpoint
CREATE TABLE `provider_events` (
	`id` text PRIMARY KEY NOT NULL,
	`order_id` text,
	`provider` text NOT NULL,
	`event_type` text NOT NULL,
	`provider_payment_id` text NOT NULL,
	`payload_hash` text NOT NULL,
	`payment_mode` text NOT NULL,
	`provider_test` integer,
	`received_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "provider_events_payment_mode_valid" CHECK("provider_events"."payment_mode" IN ('test', 'live'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `provider_events_delivery_unique` ON `provider_events` (`provider`,`event_type`,`provider_payment_id`,`payload_hash`);--> statement-breakpoint
CREATE INDEX `provider_events_payment_idx` ON `provider_events` (`provider_payment_id`,`received_at`);--> statement-breakpoint
CREATE TABLE `rate_limit_buckets` (
	`id` text PRIMARY KEY NOT NULL,
	`scope` text NOT NULL,
	`key_hash` text NOT NULL,
	`window_start` integer NOT NULL,
	`count` integer DEFAULT 1 NOT NULL,
	`expires_at` integer NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT "rate_limit_buckets_count_positive" CHECK("rate_limit_buckets"."count" > 0),
	CONSTRAINT "rate_limit_buckets_window_valid" CHECK("rate_limit_buckets"."expires_at" > "rate_limit_buckets"."window_start")
);
--> statement-breakpoint
CREATE UNIQUE INDEX `rate_limit_buckets_window_unique` ON `rate_limit_buckets` (`scope`,`key_hash`,`window_start`);--> statement-breakpoint
CREATE INDEX `rate_limit_buckets_cleanup_idx` ON `rate_limit_buckets` (`expires_at`);--> statement-breakpoint
CREATE TABLE `refunds` (
	`id` text PRIMARY KEY NOT NULL,
	`order_id` text NOT NULL,
	`provider` text DEFAULT 'yookassa' NOT NULL,
	`provider_refund_id` text,
	`amount_kopecks` integer NOT NULL,
	`currency` text DEFAULT 'RUB' NOT NULL,
	`payment_mode` text NOT NULL,
	`provider_test` integer,
	`status` text DEFAULT 'pending' NOT NULL,
	`reason` text,
	`requested_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`settled_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`order_id`) REFERENCES `orders`(`id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "refunds_amount_positive" CHECK("refunds"."amount_kopecks" > 0),
	CONSTRAINT "refunds_currency_rub" CHECK("refunds"."currency" = 'RUB'),
	CONSTRAINT "refunds_payment_mode_valid" CHECK("refunds"."payment_mode" IN ('test', 'live')),
	CONSTRAINT "refunds_status_valid" CHECK("refunds"."status" IN ('pending', 'succeeded', 'canceled', 'failed'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `refunds_provider_refund_id_unique` ON `refunds` (`provider_refund_id`);--> statement-breakpoint
CREATE INDEX `refunds_order_created_idx` ON `refunds` (`order_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `source_matches` (
	`id` text PRIMARY KEY NOT NULL,
	`match_id` text NOT NULL,
	`normalizer_version` text NOT NULL,
	`source_provider` text DEFAULT 'opendota' NOT NULL,
	`source_status` text DEFAULT 'pending' NOT NULL,
	`parser_version` text,
	`normalized_payload` text,
	`payload_hash` text,
	`fetched_at` text,
	`normalized_at` text,
	`last_checked_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT "source_matches_status_valid" CHECK("source_matches"."source_status" IN ('pending', 'fetched', 'normalized', 'unavailable', 'failed'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `source_matches_match_normalizer_unique` ON `source_matches` (`match_id`,`normalizer_version`);--> statement-breakpoint
CREATE INDEX `source_matches_status_checked_idx` ON `source_matches` (`source_status`,`last_checked_at`);--> statement-breakpoint
-- Establish an immutable opening balance for accounts created before the
-- ledger existed. This is a migration snapshot, not reconstructed order proof.
INSERT OR IGNORE INTO `entitlement_ledger` (
	`id`, `user_id`, `entry_type`, `resource`, `bucket_key`, `delta`,
	`idempotency_key`, `reference_type`, `reference_id`, `product_code`, `product_version`
)
SELECT
	'legacy-analysis-' || `id`, `id`, 'grant', 'analysis',
	'legacy-permanent:' || `id`, `analysis_credits`,
	'legacy-user:' || `id` || ':analysis', 'legacy_migration', `id`, 'legacy_balance', '0001'
FROM `users` WHERE `analysis_credits` > 0;--> statement-breakpoint
INSERT OR IGNORE INTO `entitlement_ledger` (
	`id`, `user_id`, `entry_type`, `resource`, `bucket_key`, `delta`,
	`idempotency_key`, `reference_type`, `reference_id`, `product_code`, `product_version`
)
SELECT
	'legacy-question-' || `id`, `id`, 'grant', 'coach_question',
	'legacy-permanent:' || `id`, `coach_questions_remaining`,
	'legacy-user:' || `id` || ':question', 'legacy_migration', `id`, 'legacy_balance', '0001'
FROM `users` WHERE `coach_questions_remaining` > 0;--> statement-breakpoint
INSERT OR IGNORE INTO `entitlement_ledger` (
	`id`, `user_id`, `entry_type`, `resource`, `bucket_key`, `delta`,
	`idempotency_key`, `reference_type`, `reference_id`, `product_code`, `product_version`, `expires_at`
)
SELECT
	'legacy-sub-analysis-' || `id`, `id`, 'grant', 'analysis',
	'legacy-subscription:' || `id`, `subscription_analysis_credits`,
	'legacy-user:' || `id` || ':subscription-analysis', 'legacy_migration', `id`,
	`plan_code`, '0001', `plan_expires_at`
FROM `users` WHERE `subscription_analysis_credits` > 0;--> statement-breakpoint
INSERT OR IGNORE INTO `entitlement_ledger` (
	`id`, `user_id`, `entry_type`, `resource`, `bucket_key`, `delta`,
	`idempotency_key`, `reference_type`, `reference_id`, `product_code`, `product_version`, `expires_at`
)
SELECT
	'legacy-sub-question-' || `id`, `id`, 'grant', 'coach_question',
	'legacy-subscription:' || `id`, `subscription_coach_questions_remaining`,
	'legacy-user:' || `id` || ':subscription-question', 'legacy_migration', `id`,
	`plan_code`, '0001', `plan_expires_at`
FROM `users` WHERE `subscription_coach_questions_remaining` > 0;
