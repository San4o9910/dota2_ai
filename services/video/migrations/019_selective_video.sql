-- Existing full-frame jobs retain their original contract and results.
ALTER TABLE video_jobs
    ADD COLUMN analysis_mode text NOT NULL DEFAULT 'full_frames_v1'
        CHECK (analysis_mode IN ('full_frames_v1','selective_v1')),
    ADD COLUMN hero text CHECK (length(hero) BETWEEN 1 AND 80),
    ADD COLUMN position integer CHECK (position BETWEEN 1 AND 5),
    ADD COLUMN mmr integer CHECK (mmr BETWEEN 0 AND 20000),
    ADD COLUMN training_level text CHECK (training_level IN ('foundations','application','advanced')),
    ADD COLUMN analysis_phase text NOT NULL DEFAULT 'upload',
    ADD COLUMN pipeline_version text,
    ADD COLUMN context_sha256 text,
    ADD COLUMN video_plan jsonb,
    ADD COLUMN video_coaching jsonb,
    ADD COLUMN completed_stages integer NOT NULL DEFAULT 0 CHECK (completed_stages>=0),
    ADD COLUMN total_stages integer NOT NULL DEFAULT 0 CHECK (total_stages BETWEEN 0 AND 12);

CREATE TABLE video_analysis_steps (
    job_id uuid NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    step_key text NOT NULL CHECK (length(step_key) BETWEEN 1 AND 40),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    call_id bigint NOT NULL UNIQUE REFERENCES video_provider_calls(id),
    phase text NOT NULL CHECK (phase IN ('overview','episode')),
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved','ready','failed')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY(job_id,step_key),
    CHECK (state<>'ready' OR (result IS NOT NULL AND finished_at IS NOT NULL))
);

ALTER TABLE video_provider_calls
    ADD COLUMN input_token_bound integer,
    ADD COLUMN output_token_bound integer,
    ADD COLUMN thought_token_bound integer;
