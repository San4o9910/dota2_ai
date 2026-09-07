-- Owner reflections are deliberately separate from replay-derived facts.
CREATE TABLE hero_pool_match_notes (
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    match_id text NOT NULL CHECK (match_id ~ '^[1-9][0-9]{7,11}$'),
    position integer CHECK (position BETWEEN 1 AND 5),
    focus text CHECK (focus IN ('item_plan', 'farm_checkpoint', 'safe_return')),
    reflection text CHECK (reflection IN ('done', 'partial', 'not_done')),
    note text NOT NULL DEFAULT '' CHECK (length(note) <= 500),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (reflection IS NULL OR focus IS NOT NULL),
    PRIMARY KEY (owner_id, account_id, match_id)
);
CREATE INDEX replay_jobs_pool_ready ON replay_jobs
    (owner_id, account_id, match_id, updated_at DESC, id DESC)
    WHERE state = 'ready';
