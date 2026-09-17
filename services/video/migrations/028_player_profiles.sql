-- Private, editable coaching preferences; no owner defaults or backfilled answers.
CREATE TABLE player_coaching_profiles (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    questionnaire_version text NOT NULL DEFAULT 'narma.player-profile.v1',
    state text NOT NULL CHECK (state IN ('partial','ready','skipped')),
    last_step integer NOT NULL DEFAULT 0 CHECK (last_step BETWEEN 0 AND 16),
    answers jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(answers)='object'),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE learning_plans ADD COLUMN coaching_profile jsonb NOT NULL DEFAULT '{}';
ALTER TABLE coach_chat_turns ADD COLUMN coaching_profile jsonb NOT NULL DEFAULT '{}';
