CREATE TABLE video_budget_operations (
    operation text PRIMARY KEY,
    note text NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- The first pipeline probe returned undocumented Interactions usage fields.
-- Retain its full $1.20 reservation. This acknowledges switching endpoints;
-- it does not refund, settle, delete, or reset any prior provider expenditure.
INSERT INTO video_budget_operations(operation,note,snapshot)
SELECT 'generate_content_cutover_v1',
    'Interactions probe remains unknown with its full reservation; future requests use raw GenerateContent metadata.',
    jsonb_build_object('spent_microusd',spent_microusd,'reserved_microusd',reserved_microusd,'limit_microusd',limit_microusd)
FROM video_ai_budget
WHERE id=1 AND NOT enabled AND frozen_reason='INVALID_PROVIDER_USAGE'
    AND reserved_microusd=1200000 AND spent_microusd=100000 AND limit_microusd=10000000
    AND (SELECT count(*) FROM video_provider_calls)=1
    AND EXISTS(SELECT 1 FROM video_provider_calls WHERE owner_id='narma_system_pipeline_check'
        AND first_frame=0 AND last_frame=3 AND billing_status='unknown' AND reserved_microusd=1200000
        AND usage ? 'model_invocation_token_counts' AND usage ? 'raw_prompt_token'
        AND usage->>'total_input_tokens'='4877' AND usage->>'total_output_tokens'='80'
        AND usage->>'total_thought_tokens'='88' AND usage->>'total_tokens'='5045');
UPDATE video_ai_budget SET enabled=true,frozen_reason=NULL,updated_at=now()
WHERE id=1 AND EXISTS(SELECT 1 FROM video_budget_operations WHERE operation='generate_content_cutover_v1');
