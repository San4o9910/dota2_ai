-- Player identity remains the replay-bound Steam account, never a nickname.
-- Metadata belongs to a match, so re-uploading cannot multiply its statistics.
-- The deployed reflection form stays live while this migration is applied.
-- Hold its writes until both the backfill and synchronization triggers exist.
LOCK TABLE hero_pool_match_notes IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE hero_pool_matches (
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    match_id text NOT NULL CHECK (match_id ~ '^[1-9][0-9]{7,11}$'),
    position smallint CHECK (position BETWEEN 1 AND 5),
    played_at timestamptz,
    first_analyzed_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, account_id, match_id)
);
CREATE TABLE hero_pool_favorites (
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    hero text NOT NULL CHECK (hero ~ '^npc_dota_hero_[a-z0-9_]{1,80}$'),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, account_id, hero, position)
);
CREATE TABLE hero_pool_goals (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL,
    hero text NOT NULL,
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 5),
    pattern_id text NOT NULL CHECK (pattern_id IN ('repeat-death','item-delay')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
    title text NOT NULL,
    action text NOT NULL,
    metric text NOT NULL,
    threshold double precision NOT NULL,
    baseline_match_ids jsonb NOT NULL CHECK (jsonb_typeof(baseline_match_ids)='array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX hero_pool_one_active_goal ON hero_pool_goals(owner_id,account_id,hero,position,pattern_id)
    WHERE status='active';
CREATE TABLE hero_pool_goal_checks (
    goal_id uuid NOT NULL REFERENCES hero_pool_goals(id) ON DELETE CASCADE,
    match_id text NOT NULL,
    value double precision,
    status text NOT NULL CHECK (status IN ('reached','review','unknown','predates_goal')),
    chronology_basis text NOT NULL CHECK (chronology_basis IN ('replay','user','analysis')),
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (goal_id,match_id)
);

-- Older reports only retain their last saved timestamp. Capture the first ready
-- transition from now on, independent of whether the owner visits this page.
INSERT INTO hero_pool_matches(owner_id,account_id,match_id,first_analyzed_at)
SELECT owner_id,account_id,match_id,min(updated_at) FROM replay_jobs
WHERE state='ready' AND result_payload->>'schema_version'='narma.replay-report.v1'
    AND result_payload#>>'{coverage,complete}'='true'
GROUP BY owner_id,account_id,match_id ON CONFLICT DO NOTHING;

CREATE FUNCTION hero_pool_capture_ready() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' AND OLD.state='ready' THEN
        RETURN NEW;
    END IF;
    IF NEW.state='ready' AND NEW.result_payload->>'schema_version'='narma.replay-report.v1'
       AND NEW.result_payload#>>'{coverage,complete}'='true' THEN
        INSERT INTO hero_pool_matches(owner_id,account_id,match_id,first_analyzed_at)
        VALUES (NEW.owner_id,NEW.account_id,NEW.match_id,NEW.updated_at)
        ON CONFLICT(owner_id,account_id,match_id) DO UPDATE
            SET first_analyzed_at=least(hero_pool_matches.first_analyzed_at,excluded.first_analyzed_at);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER hero_pool_ready_capture AFTER INSERT OR UPDATE OF state ON replay_jobs
FOR EACH ROW EXECUTE FUNCTION hero_pool_capture_ready();

-- Migration 007 was deployed by the previous version. Its reflections and
-- positions remain authoritative user input; add progress without rewriting it.
INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
SELECT n.owner_id,n.account_id,n.match_id,n.position,min(r.updated_at)
FROM hero_pool_match_notes n JOIN replay_jobs r ON r.owner_id=n.owner_id
    AND r.account_id=n.account_id AND r.match_id=n.match_id AND r.state<>'deleted'
GROUP BY n.owner_id,n.account_id,n.match_id,n.position
ON CONFLICT(owner_id,account_id,match_id) DO UPDATE SET position=excluded.position;

CREATE FUNCTION hero_pool_sync_note_position() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE first_saved timestamptz;
BEGIN
    IF pg_trigger_depth()>1 THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE' AND NEW.position IS NOT DISTINCT FROM OLD.position THEN RETURN NEW; END IF;
    SELECT min(updated_at) INTO first_saved FROM replay_jobs WHERE owner_id=NEW.owner_id
        AND account_id=NEW.account_id AND match_id=NEW.match_id AND state<>'deleted';
    IF first_saved IS NOT NULL THEN
        INSERT INTO hero_pool_matches(owner_id,account_id,match_id,position,first_analyzed_at)
        VALUES (NEW.owner_id,NEW.account_id,NEW.match_id,NEW.position,first_saved)
        ON CONFLICT(owner_id,account_id,match_id) DO UPDATE SET position=excluded.position,updated_at=now();
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER hero_pool_note_position_sync AFTER INSERT OR UPDATE OF position ON hero_pool_match_notes
FOR EACH ROW EXECUTE FUNCTION hero_pool_sync_note_position();

CREATE FUNCTION hero_pool_sync_progress_position() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF pg_trigger_depth()>1 THEN RETURN NEW; END IF;
    IF TG_OP='INSERT' AND NEW.position IS NULL THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE' AND NEW.position IS NOT DISTINCT FROM OLD.position THEN RETURN NEW; END IF;
    INSERT INTO hero_pool_match_notes(owner_id,account_id,match_id,position)
    VALUES (NEW.owner_id,NEW.account_id,NEW.match_id,NEW.position)
    ON CONFLICT(owner_id,account_id,match_id) DO UPDATE SET position=excluded.position,updated_at=now();
    RETURN NEW;
END $$;
CREATE TRIGGER hero_pool_progress_position_sync AFTER INSERT OR UPDATE OF position ON hero_pool_matches
FOR EACH ROW EXECUTE FUNCTION hero_pool_sync_progress_position();
