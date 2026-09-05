-- Drizzle metadata records the self-reference/check added to the 0001 table.
-- Runtime guards live here and do not rebuild the ledger under D1's implicit
-- migration transaction.
CREATE TRIGGER `entitlement_ledger_resolution_guard`
BEFORE INSERT ON `entitlement_ledger`
WHEN NEW.`resolution_of` IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM `entitlement_ledger` AS reservation
    WHERE reservation.`id` = NEW.`resolution_of`
      AND reservation.`entry_type` = 'reserve'
      AND reservation.`user_id` IS NEW.`user_id`
      AND reservation.`resource` = NEW.`resource`
      AND reservation.`bucket_key` = NEW.`bucket_key`
      AND reservation.`delta` < 0
      AND (
        (NEW.`entry_type` = 'consume' AND NEW.`delta` = 0)
        OR (NEW.`entry_type` = 'release' AND NEW.`delta` = -reservation.`delta`)
      )
      AND reservation.`order_id` IS NEW.`order_id`
      AND reservation.`reference_type` = NEW.`reference_type`
      AND reservation.`reference_id` = NEW.`reference_id`
      AND reservation.`product_code` IS NEW.`product_code`
      AND reservation.`product_version` IS NEW.`product_version`
      AND reservation.`expires_at` IS NEW.`expires_at`
  )
BEGIN
  SELECT RAISE(ABORT, 'invalid entitlement reservation resolution');
END;--> statement-breakpoint
CREATE TRIGGER `entitlement_ledger_immutable_update`
BEFORE UPDATE ON `entitlement_ledger`
WHEN NOT (
  OLD.`user_id` IS NOT NULL AND NEW.`user_id` IS NULL
  AND NEW.`id` IS OLD.`id`
  AND NEW.`order_id` IS OLD.`order_id`
  AND NEW.`entry_type` IS OLD.`entry_type`
  AND NEW.`resource` IS OLD.`resource`
  AND NEW.`bucket_key` IS OLD.`bucket_key`
  AND NEW.`delta` IS OLD.`delta`
  AND NEW.`idempotency_key` IS OLD.`idempotency_key`
  AND NEW.`reference_type` IS OLD.`reference_type`
  AND NEW.`reference_id` IS OLD.`reference_id`
  AND NEW.`resolution_of` IS OLD.`resolution_of`
  AND NEW.`product_code` IS OLD.`product_code`
  AND NEW.`product_version` IS OLD.`product_version`
  AND NEW.`expires_at` IS OLD.`expires_at`
  AND NEW.`created_at` IS OLD.`created_at`
)
BEGIN
  SELECT RAISE(ABORT, 'entitlement ledger is immutable');
END;--> statement-breakpoint
CREATE TRIGGER `entitlement_ledger_immutable_delete`
BEFORE DELETE ON `entitlement_ledger`
BEGIN
  SELECT RAISE(ABORT, 'entitlement ledger is immutable');
END;--> statement-breakpoint
CREATE TRIGGER `provider_events_immutable_update`
BEFORE UPDATE ON `provider_events`
BEGIN
  SELECT RAISE(ABORT, 'provider event is immutable');
END;--> statement-breakpoint
CREATE TRIGGER `provider_events_immutable_delete`
BEFORE DELETE ON `provider_events`
BEGIN
  SELECT RAISE(ABORT, 'provider event is immutable');
END;--> statement-breakpoint
CREATE TRIGGER `analysis_reports_immutable_update`
BEFORE UPDATE ON `analysis_reports`
BEGIN
  SELECT RAISE(ABORT, 'analysis report is immutable');
END;--> statement-breakpoint
CREATE TRIGGER `analysis_reports_immutable_delete`
BEFORE DELETE ON `analysis_reports`
BEGIN
  SELECT RAISE(ABORT, 'analysis report is immutable');
END;
