-- Personal practice is explicitly self-reported. These rows never certify
-- opportunity detection, correctness of a decision, or mastery of a skill.
CREATE TABLE learning_plans (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    hero text NOT NULL CHECK (hero ~ '^npc_dota_hero_[a-z0-9_]{1,80}$'),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    exercise_id text NOT NULL,
    curriculum_version text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
    source_job_id uuid NOT NULL REFERENCES replay_jobs(id),
    source_match_id text NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[a-f0-9]{64}$'),
    baseline_match_ids jsonb NOT NULL CHECK (jsonb_typeof(baseline_match_ids)='array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX learning_one_active_focus
    ON learning_plans(owner_id,account_id,hero,position) WHERE status='active';
CREATE INDEX learning_owner_history ON learning_plans(owner_id,account_id,created_at DESC);

CREATE TABLE learning_checks (
    plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE CASCADE,
    match_id text NOT NULL,
    job_id uuid NOT NULL REFERENCES replay_jobs(id),
    evidence_id text,
    answer text NOT NULL CHECK (length(btrim(answer)) BETWEEN 1 AND 1500),
    self_assessment text NOT NULL CHECK (self_assessment IN
        ('applied','partial','not_applied','no_opportunity','uncertain')),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[a-f0-9]{64}$'),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(plan_id,match_id)
);
