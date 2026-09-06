CREATE TABLE `dota_match_targets` (
	`user_id` text NOT NULL,
	`match_id` text NOT NULL,
	`account_id` integer NOT NULL,
	`player_slot` integer NOT NULL,
	`hero_id` integer NOT NULL,
	PRIMARY KEY(`user_id`, `match_id`),
	FOREIGN KEY (`user_id`) REFERENCES `dota_player_profiles`(`user_id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "dota_target_slot_valid" CHECK("dota_match_targets"."player_slot" IN (0,1,2,3,4,128,129,130,131,132))
);
--> statement-breakpoint
CREATE TABLE `dota_player_profiles` (
	`user_id` text PRIMARY KEY NOT NULL,
	`account_id` integer NOT NULL,
	`nickname` text NOT NULL,
	`source_match_id` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE restrict,
	CONSTRAINT "dota_profile_account_valid" CHECK("dota_player_profiles"."account_id" BETWEEN 1 AND 4294967294)
);
--> statement-breakpoint
ALTER TABLE `replay_uploads` ADD `identity_payload` text;
--> statement-breakpoint
CREATE TRIGGER dota_profile_identity_immutable BEFORE UPDATE OF user_id,account_id ON dota_player_profiles
WHEN NEW.user_id<>OLD.user_id OR NEW.account_id<>OLD.account_id
BEGIN SELECT RAISE(ABORT,'dota_profile_identity_immutable'); END;
--> statement-breakpoint
CREATE TRIGGER dota_profile_no_unlink BEFORE DELETE ON dota_player_profiles
BEGIN SELECT RAISE(ABORT,'dota_profile_no_unlink'); END;
--> statement-breakpoint
CREATE TRIGGER dota_target_identity_guard BEFORE INSERT ON dota_match_targets
WHEN NOT EXISTS(SELECT 1 FROM dota_player_profiles WHERE user_id=NEW.user_id AND account_id=NEW.account_id)
BEGIN SELECT RAISE(ABORT,'dota_target_identity_mismatch'); END;
--> statement-breakpoint
CREATE TRIGGER dota_target_immutable BEFORE UPDATE ON dota_match_targets
BEGIN SELECT RAISE(ABORT,'dota_target_immutable'); END;
