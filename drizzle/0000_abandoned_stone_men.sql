CREATE TABLE `auth_identities` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`provider` text NOT NULL,
	`provider_subject` text NOT NULL,
	`email` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`last_seen_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `auth_provider_subject_unique` ON `auth_identities` (`provider`,`provider_subject`);--> statement-breakpoint
CREATE TABLE `orders` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`product_code` text NOT NULL,
	`checkout_attempt_id` text NOT NULL,
	`match_id` text,
	`amount_kopecks` integer NOT NULL,
	`status` text DEFAULT 'created' NOT NULL,
	`yookassa_payment_id` text,
	`credited_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `orders_checkout_attempt_id_unique` ON `orders` (`checkout_attempt_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `orders_yookassa_payment_id_unique` ON `orders` (`yookassa_payment_id`);--> statement-breakpoint
CREATE INDEX `orders_user_created_idx` ON `orders` (`user_id`,`created_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `orders_one_open_coach_per_user` ON `orders` (`user_id`) WHERE 
        product_code = 'coach_30_days'
        AND status IN ('created', 'pending', 'waiting_for_capture')
      ;--> statement-breakpoint
CREATE TABLE `users` (
	`id` text PRIMARY KEY NOT NULL,
	`display_name` text NOT NULL,
	`status` text DEFAULT 'active' NOT NULL,
	`plan_code` text DEFAULT 'free_trial' NOT NULL,
	`subscription_analysis_credits` integer DEFAULT 0 NOT NULL,
	`subscription_coach_questions_remaining` integer DEFAULT 0 NOT NULL,
	`analysis_credits` integer DEFAULT 1 NOT NULL,
	`coach_questions_remaining` integer DEFAULT 5 NOT NULL,
	`plan_expires_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
