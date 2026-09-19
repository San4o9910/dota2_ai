-- A player has one selected practice, while older plans retain their history.
CREATE TABLE player_program_focus (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE CASCADE,
    updated_at timestamptz NOT NULL DEFAULT now()
);
