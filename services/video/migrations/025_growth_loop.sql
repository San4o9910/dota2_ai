-- No provider is activated and no existing allowance or ledger is changed.
ALTER TABLE coach_chat_turns
    ADD COLUMN scope text NOT NULL DEFAULT 'replay' CHECK (scope IN ('replay','series')),
    ADD COLUMN sources jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(sources)='array'),
    ADD COLUMN practice_context jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(practice_context)='array');
CREATE INDEX coach_chat_series_history ON coach_chat_turns(owner_id,account_id,created_at DESC) WHERE scope='series';

CREATE TABLE coaching_feedback (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[a-f0-9]{64}$'),
    position smallint CHECK (position BETWEEN 1 AND 5),
    point_index smallint CHECK (point_index>=0),
    reason text NOT NULL CHECK (reason IN ('context','role','generic','facts','helpful')),
    comment text NOT NULL CHECK (length(comment)<=1500),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX coaching_feedback_owner ON coaching_feedback(owner_id,job_id,created_at DESC);

CREATE TABLE replay_practice_attempts (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[a-f0-9]{64}$'),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    exercise_id text NOT NULL,
    evidence_id text NOT NULL,
    answer text NOT NULL CHECK (length(btrim(answer)) BETWEEN 10 AND 1500),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX replay_practice_history ON replay_practice_attempts(owner_id,job_id,created_at DESC);

-- Optional cumulative ceiling across the two funded provider ledgers.
-- NULL preserves the shared global budgets and existing daily request limits.
CREATE TABLE owner_ai_limits (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    limit_microusd bigint CHECK (limit_microusd BETWEEN 0 AND 1000000000),
    updated_at timestamptz NOT NULL DEFAULT now()
);
