-- Owner-funded API calls have a monetary ledger separate from personal OAuth
-- and Gemini. Installing this migration does not authorize or enable spending.
CREATE TABLE openai_api_budget (
    id smallint PRIMARY KEY CHECK (id=1),
    model text NOT NULL,
    price_policy text NOT NULL,
    expires_at timestamptz NOT NULL,
    limit_microusd bigint NOT NULL DEFAULT 0 CHECK (limit_microusd BETWEEN 0 AND 10000000),
    spent_microusd bigint NOT NULL DEFAULT 0 CHECK (spent_microusd>=0),
    reserved_microusd bigint NOT NULL DEFAULT 0 CHECK (reserved_microusd>=0),
    enabled boolean NOT NULL DEFAULT false,
    frozen_reason text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO openai_api_budget(id,model,price_policy,expires_at)
VALUES (1,'gpt-5.6-sol','gpt-5.6-sol-standard-2026-09-12','2026-11-21T00:00:00Z');

CREATE TABLE openai_api_calls (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    request_key text NOT NULL CHECK (length(request_key) BETWEEN 1 AND 180),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    kind text NOT NULL CHECK (kind IN ('replay','video','hermes')),
    job_id uuid,
    video_job_id uuid,
    task_id uuid,
    lease_token uuid NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    budget_id smallint NOT NULL REFERENCES openai_api_budget(id),
    model text NOT NULL,
    price_policy text NOT NULL,
    input_token_bound integer NOT NULL CHECK (input_token_bound BETWEEN 1 AND 240000),
    max_output_tokens integer NOT NULL CHECK (max_output_tokens BETWEEN 256 AND 8192),
    reserved_microusd bigint NOT NULL CHECK (reserved_microusd>0),
    charged_microusd bigint CHECK (charged_microusd>=0),
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','calling','succeeded','failed','unknown')),
    billing_status text NOT NULL DEFAULT 'reserved' CHECK (billing_status IN ('reserved','settled','unknown','breach')),
    usage jsonb CHECK (usage IS NULL OR jsonb_typeof(usage)='object'),
    output_text text CHECK (output_text IS NULL OR octet_length(output_text)<=100000),
    output_sha256 text CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes',
    finished_at timestamptz,
    UNIQUE(owner_id,request_key),
    CHECK ((kind='replay' AND job_id IS NOT NULL AND video_job_id IS NULL AND task_id IS NULL)
        OR (kind='video' AND video_job_id IS NOT NULL AND job_id IS NULL AND task_id IS NULL)
        OR (kind='hermes' AND task_id IS NOT NULL AND job_id IS NULL AND video_job_id IS NULL)),
    CHECK (state<>'calling' OR started_at IS NOT NULL),
    CHECK (state<>'succeeded' OR (output_text IS NOT NULL AND output_sha256 IS NOT NULL
        AND finished_at IS NOT NULL AND billing_status='settled')),
    CHECK (state IN ('reserved','calling') OR finished_at IS NOT NULL)
);
-- One paid coaching attempt per source. A crash or unknown charge cannot become
-- another paid attempt merely by changing the request key or reclaiming a job.
CREATE UNIQUE INDEX openai_api_calls_replay_once ON openai_api_calls(job_id) WHERE job_id IS NOT NULL;
CREATE UNIQUE INDEX openai_api_calls_video_once ON openai_api_calls(video_job_id) WHERE video_job_id IS NOT NULL;
CREATE UNIQUE INDEX openai_api_calls_task_once ON openai_api_calls(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX openai_api_calls_owner_day ON openai_api_calls(owner_id,created_at);
