ALTER TABLE `analysis_reports` ADD `normalized_payload` text;--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `normalized_payload` text;--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `lease_token` text;--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `lease_expires_at` text;--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `attempt` integer DEFAULT 0 NOT NULL;