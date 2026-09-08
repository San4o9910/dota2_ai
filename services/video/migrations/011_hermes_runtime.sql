-- Keep task attribution and billing history even if a player removes a report.
-- Source ownership is checked against the current binding before every call/read.
CREATE TABLE hermes_tasks (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=393216),
    source_jobs jsonb NOT NULL CHECK (jsonb_typeof(source_jobs)='object'),
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','succeeded','failed','stale')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 1),
    lease_token uuid,
    credential_sha256 text UNIQUE CHECK (credential_sha256 ~ '^[0-9a-f]{64}$'),
    lease_until timestamptz,
    review jsonb CHECK (jsonb_typeof(review)='object' AND octet_length(review::text)<=32768),
    runtime_revision text CHECK (runtime_revision ~ '^[0-9a-f]{40}$'),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE(owner_id,account_id,snapshot_sha256),
    CHECK (state<>'running' OR (attempts=1 AND lease_token IS NOT NULL AND credential_sha256 IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK (state<>'succeeded' OR (review IS NOT NULL AND runtime_revision IS NOT NULL AND finished_at IS NOT NULL))
);
CREATE INDEX hermes_tasks_pending ON hermes_tasks(created_at,id) WHERE state='queued';
CREATE INDEX hermes_tasks_owner_recent ON hermes_tasks(owner_id,account_id,created_at DESC);
CREATE TABLE hermes_workers (
    id text PRIMARY KEY CHECK (id='scheduler'),
    runtime_revision text NOT NULL CHECK (runtime_revision ~ '^[0-9a-f]{40}$'),
    automatic_tracking boolean NOT NULL,
    last_seen timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE video_provider_calls
    ADD COLUMN hermes_task_id uuid REFERENCES hermes_tasks(id),
    DROP CONSTRAINT provider_call_exactly_one_job,
    ADD CONSTRAINT provider_call_exactly_one_job CHECK (
        (call_kind='video' AND job_id IS NOT NULL AND replay_job_id IS NULL AND hermes_task_id IS NULL)
        OR (call_kind='replay' AND job_id IS NULL AND replay_job_id IS NOT NULL AND hermes_task_id IS NULL)
        OR (call_kind='hermes' AND job_id IS NULL AND replay_job_id IS NULL AND hermes_task_id IS NOT NULL)
    ),
    ADD CONSTRAINT hermes_call_has_no_frames CHECK (
        hermes_task_id IS NULL OR (first_frame=0 AND last_frame=0)
    );
-- An uncertain or unsuccessful paid attempt must never be retried automatically.
CREATE UNIQUE INDEX video_provider_calls_hermes_once ON video_provider_calls(hermes_task_id)
    WHERE hermes_task_id IS NOT NULL;
