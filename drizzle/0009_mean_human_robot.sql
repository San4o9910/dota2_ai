CREATE TABLE `replay_upload_parts` (
	`id` text PRIMARY KEY NOT NULL,
	`replay_id` text NOT NULL,
	`part_number` integer NOT NULL,
	`etag` text NOT NULL,
	`size_bytes` integer NOT NULL,
	FOREIGN KEY (`replay_id`) REFERENCES `replay_uploads`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `replay_parts_number_idx` ON `replay_upload_parts` (`replay_id`,`part_number`);--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `upload_id` text;