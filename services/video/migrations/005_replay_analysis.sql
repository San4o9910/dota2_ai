-- Private replay uploads and the full .dem analysis queue. No provider budget
-- dependency: gameplay data comes from the local Source 2 parser.
CREATE TABLE replay_jobs (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    filename text NOT NULL CHECK (length(filename) BETWEEN 5 AND 180),
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 20 AND 536870912),
    requested_nickname text NOT NULL CHECK (length(requested_nickname) BETWEEN 1 AND 128),
    nickname text NOT NULL CHECK (length(nickname) BETWEEN 1 AND 128),
    expected_match_id text CHECK (expected_match_id ~ '^[1-9][0-9]{7,11}$'),
    match_id text CHECK (match_id ~ '^[1-9][0-9]{7,11}$'),
    account_id bigint CHECK (account_id BETWEEN 1 AND 4294967294),
    source_sha256 text CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL DEFAULT 'uploading' CHECK (state IN ('uploading','queued','processing','ready','failed','deleted')),
    progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    result_payload jsonb,
    failure_code text,
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    lease_token uuid,
    lease_expires_at timestamptz,
    storage_deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (state NOT IN ('queued','processing','ready') OR (account_id IS NOT NULL AND match_id IS NOT NULL AND source_sha256 IS NOT NULL)),
    CHECK (state <> 'ready' OR (result_payload IS NOT NULL AND progress=100))
);
CREATE INDEX replay_jobs_owner_time ON replay_jobs(owner_id,created_at DESC);
CREATE INDEX replay_jobs_queue ON replay_jobs(state,created_at);
CREATE TABLE replay_parts (
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    part_number integer NOT NULL CHECK (part_number BETWEEN 1 AND 103),
    size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND 5242880),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (job_id,part_number)
);
CREATE TABLE replay_workers (
    id text PRIMARY KEY,
    last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION replay_identity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.filename IS DISTINCT FROM OLD.filename OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
       OR NEW.requested_nickname IS DISTINCT FROM OLD.requested_nickname
       OR NEW.expected_match_id IS DISTINCT FROM OLD.expected_match_id
       OR (OLD.account_id IS NOT NULL AND NEW.account_id IS DISTINCT FROM OLD.account_id)
       OR (OLD.match_id IS NOT NULL AND NEW.match_id IS DISTINCT FROM OLD.match_id)
       OR (OLD.source_sha256 IS NOT NULL AND NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256) THEN
        RAISE EXCEPTION 'replay identity and source are immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER replay_identity_guard BEFORE UPDATE ON replay_jobs
FOR EACH ROW EXECUTE FUNCTION replay_identity_immutable();
