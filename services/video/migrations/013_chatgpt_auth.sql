-- Owner's explicit, personal ChatGPT/Codex OAuth connection. No provider key.
-- Both pending device credentials and issued tokens are authenticated-encrypted
-- by the application; ciphertext also binds owner_id and generation.
CREATE TABLE chatgpt_connections (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    generation uuid NOT NULL,
    state text NOT NULL CHECK (state IN ('disconnected','pending','connected','expired','reconnect_required')),
    secret_ciphertext text,
    connected_at timestamptz,
    expires_at timestamptz,
    next_poll_at timestamptz,
    poll_interval_seconds integer NOT NULL DEFAULT 5 CHECK (poll_interval_seconds BETWEEN 3 AND 60),
    quota_paused boolean NOT NULL DEFAULT false,
    paused_until timestamptz,
    last_error_code text,
    rotation_started_at timestamptz,
    rotation_kind text CHECK (rotation_kind IN ('exchange','refresh')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((state IN ('pending','connected')) = (secret_ciphertext IS NOT NULL)),
    CHECK (state <> 'pending' OR (expires_at IS NOT NULL AND next_poll_at IS NOT NULL)),
    CHECK ((rotation_started_at IS NULL) = (rotation_kind IS NULL)),
    CHECK (secret_ciphertext IS NULL OR length(secret_ciphertext) BETWEEN 32 AND 65536)
);
