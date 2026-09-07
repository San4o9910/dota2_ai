-- Keep the existing global allowance, historical charges and uncertain reservations.
-- This migration only permits the same accounting ledger to reference replay jobs.
ALTER TABLE video_provider_calls
    ALTER COLUMN job_id DROP NOT NULL,
    ADD COLUMN replay_job_id uuid REFERENCES replay_jobs(id),
    ADD COLUMN call_kind text NOT NULL DEFAULT 'video',
    ADD CONSTRAINT provider_call_exactly_one_job CHECK (
        (call_kind='video' AND job_id IS NOT NULL AND replay_job_id IS NULL)
        OR (call_kind='replay' AND job_id IS NULL AND replay_job_id IS NOT NULL)
    ),
    ADD CONSTRAINT replay_call_has_no_frames CHECK (
        replay_job_id IS NULL OR (first_frame=0 AND last_frame=0)
    );
CREATE INDEX video_provider_calls_replay_job ON video_provider_calls(replay_job_id)
    WHERE replay_job_id IS NOT NULL;
