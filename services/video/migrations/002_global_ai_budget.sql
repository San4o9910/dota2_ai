CREATE TABLE video_ai_budget (
    id smallint PRIMARY KEY CHECK (id=1),
    model text NOT NULL,
    price_policy text NOT NULL,
    expires_at timestamptz NOT NULL,
    limit_microusd bigint NOT NULL CHECK (limit_microusd>0),
    spent_microusd bigint NOT NULL DEFAULT 0 CHECK (spent_microusd>=0),
    reserved_microusd bigint NOT NULL DEFAULT 0 CHECK (reserved_microusd>=0),
    accounting_rub_per_usd integer NOT NULL CHECK (accounting_rub_per_usd>0),
    enabled boolean NOT NULL DEFAULT true,
    frozen_reason text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- $0.10 covers the two earlier, recorded image checks ($0.00904125 token estimate).
-- The 200 RUB/USD value is a conservative internal conversion, not a live FX quote.
INSERT INTO video_ai_budget(id,model,price_policy,expires_at,limit_microusd,spent_microusd,accounting_rub_per_usd)
VALUES (1,'gemini-3.8-flash','gemini-3.8-flash-standard-2026-09-07','2027-01-01T00:00:00Z',10000000,100000,200);

ALTER TABLE video_provider_calls
    ADD COLUMN budget_id smallint REFERENCES video_ai_budget(id),
    ADD COLUMN model text,
    ADD COLUMN price_policy text,
    ADD COLUMN reserved_microusd bigint NOT NULL DEFAULT 0 CHECK (reserved_microusd>=0),
    ADD COLUMN charged_microusd bigint CHECK (charged_microusd>=0),
    ADD COLUMN billing_status text NOT NULL DEFAULT 'legacy' CHECK (billing_status IN ('legacy','reserved','settled','unknown','breach')),
    ADD COLUMN usage jsonb,
    ADD COLUMN finished_at timestamptz;

-- Unpriced calls must not disappear during migration. Keep their maximum charge reserved.
UPDATE video_provider_calls SET budget_id=1, reserved_microusd=1200000, billing_status='unknown';
UPDATE video_ai_budget SET reserved_microusd=(SELECT coalesce(sum(reserved_microusd),0) FROM video_provider_calls);
UPDATE video_ai_budget SET enabled=false, frozen_reason='LEGACY_CALLS_EXCEED_BUDGET'
WHERE spent_microusd+reserved_microusd>limit_microusd;
-- Old worker versions must fail before inference instead of inserting unpriced calls.
ALTER TABLE video_provider_calls ALTER COLUMN budget_id SET NOT NULL,
    ALTER COLUMN billing_status DROP DEFAULT,
    ADD CONSTRAINT video_call_requires_reservation CHECK (reserved_microusd>0 AND billing_status<>'legacy');
