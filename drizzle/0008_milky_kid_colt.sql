CREATE TABLE `analysis_attempts` (
	`lease_token` text PRIMARY KEY NOT NULL,
	`job_id` text NOT NULL,
	`user_id` text NOT NULL,
	`started_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`job_id`) REFERENCES `analysis_jobs`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `analysis_attempts_user_time_idx` ON `analysis_attempts` (`user_id`,`started_at`);--> statement-breakpoint
CREATE INDEX `analysis_attempts_time_idx` ON `analysis_attempts` (`started_at`);--> statement-breakpoint
CREATE TABLE `coach_exchanges` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`job_id` text NOT NULL,
	`question` text NOT NULL,
	`answer` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`job_id`) REFERENCES `analysis_jobs`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `coach_exchanges_owner_time_idx` ON `coach_exchanges` (`user_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `coach_exchanges_job_time_idx` ON `coach_exchanges` (`job_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `replay_uploads` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`filename` text NOT NULL,
	`object_key` text NOT NULL,
	`size_bytes` integer NOT NULL,
	`state` text DEFAULT 'uploading' NOT NULL,
	`failure_code` text,
	`match_id` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE no action,
	CONSTRAINT "replay_uploads_state_valid" CHECK("replay_uploads"."state" IN ('uploading','uploaded','processing','ready','failed','deleted'))
);
--> statement-breakpoint
CREATE INDEX `replay_uploads_owner_time_idx` ON `replay_uploads` (`user_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `replay_uploads_state_time_idx` ON `replay_uploads` (`state`,`created_at`);--> statement-breakpoint
CREATE TABLE `training_progress` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`context_id` text NOT NULL,
	`task_id` text NOT NULL,
	`completed` integer DEFAULT false NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade,
	CONSTRAINT "training_progress_completed_valid" CHECK("training_progress"."completed" IN (0,1))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `training_progress_owner_task_idx` ON `training_progress` (`user_id`,`context_id`,`task_id`);