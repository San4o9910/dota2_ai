-- Explicit platform authority is independent from each tenant's owner_id.
-- Only an unambiguous sole legacy account becomes the platform owner. An
-- installation with multiple pre-existing accounts remains fail-closed and
-- needs an operator to designate the intended account explicitly.
ALTER TABLE portal_accounts ADD COLUMN is_platform_owner boolean NOT NULL DEFAULT false;
UPDATE portal_accounts SET is_platform_owner=true
WHERE (SELECT count(*) FROM portal_accounts)=1;
CREATE UNIQUE INDEX portal_single_platform_owner ON portal_accounts(is_platform_owner)
WHERE is_platform_owner;

CREATE TABLE portal_invitations (
    id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    invited_by text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE TABLE portal_recovery_codes (
    token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    used_at timestamptz
);
CREATE INDEX portal_recovery_owner ON portal_recovery_codes(owner_id);
