-- Cache writes cost more than ordinary input. Old reservations cannot be
-- dispatched under the new policy; preserve every charge, hold and freeze.
SELECT id FROM openai_api_budget WHERE id=1 FOR UPDATE;

UPDATE openai_api_budget AS budget
SET enabled=false,
    frozen_reason=coalesce(frozen_reason,'PRICE_POLICY_UPGRADE_REQUIRES_RECONCILIATION'),
    updated_at=now()
WHERE id=1 AND model='gpt-5.6-sol'
    AND price_policy='gpt-5.6-sol-standard-2026-09-12'
    AND (reserved_microusd<>0 OR EXISTS (
        SELECT 1 FROM openai_api_calls AS calls WHERE calls.budget_id=budget.id
            AND (calls.billing_status IN ('reserved','unknown','breach')
                OR calls.state IN ('reserved','calling','unknown'))));

-- A fresh or fully settled allowance can move forward without re-enabling
-- spending or rewriting historical calls and their original accounting policy.
UPDATE openai_api_budget AS budget
SET price_policy='gpt-5.6-sol-standard-cache-v2-2026-09-12',updated_at=now()
WHERE id=1 AND model='gpt-5.6-sol'
    AND price_policy='gpt-5.6-sol-standard-2026-09-12'
    AND reserved_microusd=0 AND NOT EXISTS (
        SELECT 1 FROM openai_api_calls AS calls WHERE calls.budget_id=budget.id
            AND (calls.billing_status IN ('reserved','unknown','breach')
                OR calls.state IN ('reserved','calling','unknown')));
