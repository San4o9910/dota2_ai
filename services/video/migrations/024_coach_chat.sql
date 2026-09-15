-- Chat uses the existing funded allowance. No budget or usage is changed.
CREATE TABLE coach_chat_turns (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    account_id bigint NOT NULL,
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[0-9a-f]{64}$'),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    context jsonb NOT NULL,
    question text NOT NULL CHECK (length(question)<=2000),
    evidence_id text,
    input_data text,
    answer jsonb,
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running','succeeded','failed','deleted')),
    error_code text,
    lease_token uuid NOT NULL,
    lease_until timestamptz NOT NULL DEFAULT now()+interval '5 minutes',
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX coach_chat_owner_history ON coach_chat_turns(owner_id,job_id,created_at);
ALTER TABLE openai_api_calls DROP CONSTRAINT openai_api_calls_kind_check,
    ADD CONSTRAINT openai_api_calls_kind_check CHECK (kind IN ('replay','video','hermes','chat'));
ALTER TABLE openai_api_calls DROP CONSTRAINT openai_api_calls_check,
    ADD CONSTRAINT openai_api_calls_check CHECK (
        (kind='replay' AND job_id IS NOT NULL AND video_job_id IS NULL AND task_id IS NULL)
        OR (kind='video' AND video_job_id IS NOT NULL AND job_id IS NULL AND task_id IS NULL)
        OR (kind IN ('hermes','chat') AND task_id IS NOT NULL AND job_id IS NULL AND video_job_id IS NULL));
