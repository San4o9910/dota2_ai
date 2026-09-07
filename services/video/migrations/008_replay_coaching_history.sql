-- Snapshot the complete report and its original evidence atomically before a
-- ready replay is refreshed. Existing support scripts need no separate backup
-- step, and a failed worker cannot erase the last useful coaching report.
CREATE TABLE replay_report_history (
    id bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    match_id text NOT NULL,
    account_id bigint NOT NULL,
    report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX replay_report_history_job ON replay_report_history(job_id,id DESC);

CREATE FUNCTION preserve_replay_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state = 'deleted' THEN
        DELETE FROM replay_report_history WHERE job_id=OLD.id;
    ELSIF OLD.state = 'ready' AND OLD.result_payload IS NOT NULL
       AND (NEW.state IS DISTINCT FROM OLD.state
            OR NEW.result_payload IS DISTINCT FROM OLD.result_payload)
       AND OLD.result_payload->>'match_id' = OLD.match_id
       AND OLD.result_payload->'player'->>'account_id' = OLD.account_id::text THEN
        INSERT INTO replay_report_history(job_id,source_sha256,match_id,account_id,report)
            VALUES (OLD.id,OLD.source_sha256,OLD.match_id,OLD.account_id,OLD.result_payload);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER replay_report_preservation BEFORE UPDATE ON replay_jobs
FOR EACH ROW EXECUTE FUNCTION preserve_replay_report();
