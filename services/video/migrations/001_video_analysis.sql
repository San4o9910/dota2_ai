CREATE TABLE video_jobs (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    nickname text NOT NULL,
    filename text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 16 AND 2147483648),
    source_sha256 text,
    storage_deleted_at timestamptz,
    state text NOT NULL DEFAULT 'uploading' CHECK (state IN ('uploading','queued','processing','ready','failed','deleted')),
    failure_code text,
    frame_count integer CHECK (frame_count BETWEEN 1 AND 432000),
    processed_frames integer NOT NULL DEFAULT 0 CHECK (processed_frames >= 0),
    duration_seconds double precision,
    first_pts_seconds double precision,
    model text,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version=1),
    attempt integer NOT NULL DEFAULT 0,
    lease_token uuid,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (frame_count IS NULL OR processed_frames <= frame_count)
);
CREATE INDEX video_jobs_owner_time ON video_jobs(owner_id,created_at DESC);
CREATE INDEX video_jobs_queue ON video_jobs(state,created_at);
CREATE TABLE video_parts (
    job_id uuid NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    part_number integer NOT NULL CHECK (part_number > 0),
    size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND 5242880),
    sha256 text NOT NULL,
    PRIMARY KEY (job_id,part_number)
);
CREATE TABLE video_batches (
    job_id uuid NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
    first_frame integer NOT NULL,
    last_frame integer NOT NULL,
    first_pts_seconds double precision NOT NULL,
    last_pts_seconds double precision NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id,first_frame),
    CHECK (first_frame >= 0 AND last_frame >= first_frame),
    CHECK (last_pts_seconds >= first_pts_seconds)
);
CREATE TABLE video_workers (
    id text PRIMARY KEY,
    model text NOT NULL,
    last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE video_provider_calls (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES video_jobs(id),
    owner_id text NOT NULL,
    first_frame integer NOT NULL,
    last_frame integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX video_provider_calls_job ON video_provider_calls(job_id);
CREATE INDEX video_provider_calls_owner_time ON video_provider_calls(owner_id,created_at);
