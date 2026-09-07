CREATE TABLE portal_accounts (
    owner_id text PRIMARY KEY,
    singleton boolean NOT NULL DEFAULT true UNIQUE CHECK (singleton),
    email text NOT NULL UNIQUE CHECK (length(email) BETWEEN 3 AND 254),
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE portal_sessions (
    token_hash text PRIMARY KEY CHECK (length(token_hash)=64),
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX portal_sessions_owner ON portal_sessions(owner_id, created_at DESC);
CREATE TABLE portal_auth_limits (
    bucket text PRIMARY KEY,
    window_started timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL CHECK (attempts > 0)
);
CREATE TABLE portal_dota_profiles (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    account_id bigint NOT NULL CHECK (account_id BETWEEN 1 AND 4294967294),
    nickname text NOT NULL CHECK (length(nickname) BETWEEN 1 AND 128),
    match_id text NOT NULL CHECK (match_id ~ '^[0-9]{8,12}$'),
    hero_name text NOT NULL,
    side text NOT NULL CHECK (side IN ('radiant','dire')),
    source_sha256 text NOT NULL CHECK (length(source_sha256)=64),
    bound_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE portal_replay_uploads (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    reserved_bytes bigint NOT NULL CHECK (reserved_bytes BETWEEN 1 AND 536870912),
    expires_at timestamptz NOT NULL
);
