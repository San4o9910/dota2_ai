-- The player's declared match context is an immutable upload snapshot. It is
-- never a verified rating, a profile-wide value or an automatic skill score.
ALTER TABLE replay_jobs
    ADD COLUMN requested_position smallint CHECK (requested_position BETWEEN 1 AND 5),
    ADD COLUMN requested_mmr integer CHECK (requested_mmr BETWEEN 0 AND 20000),
    ADD COLUMN training_level text CHECK (training_level IN ('foundations','application','advanced'));

CREATE FUNCTION replay_training_context_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.requested_position IS DISTINCT FROM OLD.requested_position
       OR NEW.requested_mmr IS DISTINCT FROM OLD.requested_mmr
       OR NEW.training_level IS DISTINCT FROM OLD.training_level THEN
        RAISE EXCEPTION 'replay training context is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER replay_training_context_guard BEFORE UPDATE ON replay_jobs
FOR EACH ROW EXECUTE FUNCTION replay_training_context_immutable();

-- The role is read from the upload while parsing a previously unseen match.
-- Only a complete ready report creates pool metadata. An existing manual role,
-- including an explicit reset to unknown, always wins on re-upload.
CREATE OR REPLACE FUNCTION hero_pool_capture_ready() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE captured_position smallint;
BEGIN
    IF TG_OP='UPDATE' AND OLD.state='ready' THEN
        RETURN NEW;
    END IF;
    IF NEW.state='ready' AND NEW.result_payload->>'schema_version'='narma.replay-report.v1'
       AND NEW.result_payload#>>'{coverage,complete}'='true' THEN
        INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
        VALUES (NEW.owner_id,NEW.account_id,NEW.match_id,NEW.requested_position,NEW.updated_at)
        ON CONFLICT(owner_id,account_id,match_id) DO UPDATE
            SET first_analyzed_at=least(hero_pool_matches.first_analyzed_at,excluded.first_analyzed_at)
        RETURNING position INTO captured_position;
        -- This function runs inside the replay ready trigger. The ordinary
        -- bidirectional position triggers intentionally stop when nested, so
        -- seed the legacy projection explicitly from the resulting role.
        -- Existing manual notes, including a cleared role, remain untouched.
        INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position)
        VALUES (NEW.owner_id,NEW.account_id,NEW.match_id,captured_position)
        ON CONFLICT(owner_id,account_id,match_id) DO NOTHING;
    END IF;
    RETURN NEW;
END $$;
