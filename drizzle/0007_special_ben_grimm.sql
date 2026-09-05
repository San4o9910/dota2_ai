ALTER TABLE `analysis_jobs` ADD `retry_not_before` text;--> statement-breakpoint
CREATE UNIQUE INDEX `analysis_jobs_active_report_identity_unique` ON `analysis_jobs` (`user_id`,`match_id`,`player_slot`,`report_version`) WHERE "analysis_jobs"."state" IN ('queued', 'running', 'ready');--> statement-breakpoint
DROP INDEX `analysis_jobs_report_identity_unique`;
