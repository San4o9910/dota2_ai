-- Subscription usage is a separate ledger: it does not settle API reservations.
CREATE TABLE chatgpt_calls (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    request_key text NOT NULL CHECK (length(request_key) BETWEEN 1 AND 180),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    job_id uuid,
    task_id uuid,
    model text NOT NULL CHECK (model='gpt-5.4'),
    connection_generation uuid NOT NULL,
    lease_token uuid NOT NULL,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','calling','succeeded','failed','unknown')),
    usage_kind text NOT NULL DEFAULT 'chatgpt_subscription' CHECK (usage_kind='chatgpt_subscription'),
    api_cost_microusd bigint CHECK (api_cost_microusd IS NULL),
    usage jsonb CHECK (usage IS NULL OR jsonb_typeof(usage)='object'),
    output_text text CHECK (output_text IS NULL OR octet_length(output_text)<=100000),
    output_sha256 text CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'),
    error_code text,
    pause_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '150 seconds',
    finished_at timestamptz,
    UNIQUE(owner_id,request_key),
    CHECK ((job_id IS NOT NULL)::integer+(task_id IS NOT NULL)::integer=1),
    CHECK (state<>'calling' OR started_at IS NOT NULL),
    CHECK (state<>'succeeded' OR (output_text IS NOT NULL AND output_sha256 IS NOT NULL AND finished_at IS NOT NULL)),
    CHECK (state IN ('reserved','calling') OR finished_at IS NOT NULL)
);
CREATE UNIQUE INDEX chatgpt_calls_task_once ON chatgpt_calls(task_id) WHERE task_id IS NOT NULL;
CREATE UNIQUE INDEX chatgpt_calls_job_once ON chatgpt_calls(job_id) WHERE job_id IS NOT NULL;
CREATE INDEX chatgpt_calls_owner_day ON chatgpt_calls(owner_id,created_at);
