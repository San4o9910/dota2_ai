-- Paid inference isolates existing client accounts by owner_id. The original
-- pilot singleton index otherwise prevents a second client from existing at all.
-- Keep the legacy column for compatibility; bootstrap setup is still one-time,
-- and this migration does not open public signup or change personal OAuth gates.
ALTER TABLE portal_accounts DROP CONSTRAINT portal_accounts_singleton_key;
