-- Create the stricter guard first. If historical semantic duplicates exist,
-- fail closed without removing the previous delivery-level protection.
CREATE UNIQUE INDEX `provider_events_transition_unique` ON `provider_events` (`provider`,`event_type`,`provider_payment_id`);--> statement-breakpoint
DROP INDEX `provider_events_delivery_unique`;--> statement-breakpoint
-- Order business identity and commercial terms are a write-once financial
-- snapshot. The user_id exception is limited to an actual parent deletion so
-- ON DELETE SET NULL can retain financial records without permitting a direct
-- ownership-detachment update while the user still exists.
CREATE TRIGGER `orders_snapshot_immutable_update`
BEFORE UPDATE ON `orders`
WHEN NEW.`id` IS NOT OLD.`id`
  OR NOT (
    NEW.`user_id` IS OLD.`user_id`
    OR (
      OLD.`user_id` IS NOT NULL
      AND NEW.`user_id` IS NULL
      AND NOT EXISTS (SELECT 1 FROM `users` WHERE `id` = OLD.`user_id`)
    )
  )
  OR NEW.`product_code` IS NOT OLD.`product_code`
  OR NEW.`product_version` IS NOT OLD.`product_version`
  OR NEW.`checkout_attempt_id` IS NOT OLD.`checkout_attempt_id`
  OR NEW.`request_hash` IS NOT OLD.`request_hash`
  OR NEW.`provider_idempotency_key` IS NOT OLD.`provider_idempotency_key`
  OR NEW.`match_id` IS NOT OLD.`match_id`
  OR NEW.`amount_kopecks` IS NOT OLD.`amount_kopecks`
  OR NEW.`currency` IS NOT OLD.`currency`
  OR NEW.`grant_analyses` IS NOT OLD.`grant_analyses`
  OR NEW.`grant_coach_questions` IS NOT OLD.`grant_coach_questions`
  OR NEW.`duration_days` IS NOT OLD.`duration_days`
  OR NEW.`environment` IS NOT OLD.`environment`
  OR NEW.`payment_mode` IS NOT OLD.`payment_mode`
  OR NEW.`provider` IS NOT OLD.`provider`
  OR NEW.`provider_shop_id` IS NOT OLD.`provider_shop_id`
  OR NEW.`created_at` IS NOT OLD.`created_at`
BEGIN
  SELECT RAISE(ABORT, 'order snapshot is immutable');
END;--> statement-breakpoint
-- Provider bindings and terminal outcomes are monotonic. Retrying checkout or
-- receiving an out-of-order notification may repeat the same value, but cannot
-- rebind a payment, clear credit evidence, or regress a terminal order.
CREATE TRIGGER `orders_lifecycle_monotonic_update`
BEFORE UPDATE ON `orders`
WHEN (OLD.`yookassa_payment_id` IS NOT NULL AND NEW.`yookassa_payment_id` IS NOT OLD.`yookassa_payment_id`)
  OR (OLD.`provider_test` IS NOT NULL AND NEW.`provider_test` IS NOT OLD.`provider_test`)
  OR (OLD.`credited_at` IS NOT NULL AND NEW.`credited_at` IS NOT OLD.`credited_at`)
  OR (OLD.`status` IN ('succeeded', 'canceled') AND NEW.`status` IS NOT OLD.`status`)
  OR (OLD.`status` = 'pending' AND NEW.`status` = 'created')
  OR (OLD.`status` = 'waiting_for_capture' AND NEW.`status` IN ('created', 'pending'))
  OR (OLD.`fulfillment_status` = 'granted' AND NEW.`fulfillment_status` <> 'granted')
  OR (
    OLD.`fulfillment_status` = 'manual_review'
    AND NEW.`fulfillment_status` NOT IN ('manual_review', 'granted')
  )
BEGIN
  SELECT RAISE(ABORT, 'order lifecycle cannot regress');
END;
