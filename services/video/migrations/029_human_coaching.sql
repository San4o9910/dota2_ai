-- Human coaching is opt-in. No existing account, replay or AI dialogue is shared.
CREATE TABLE human_coaches (
    owner_id text PRIMARY KEY REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    display_name text NOT NULL,
    experience text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','suspended')),
    revision integer NOT NULL DEFAULT 1,
    reviewed_by text REFERENCES portal_accounts(owner_id) ON DELETE SET NULL,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE coaching_links (
    id uuid PRIMARY KEY,
    coach_id text NOT NULL REFERENCES human_coaches(owner_id) ON DELETE CASCADE,
    student_id text REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    student_name text,
    status text NOT NULL DEFAULT 'invited' CHECK(status IN ('invited','active','revoked')),
    token_hash text UNIQUE,
    expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
    share_profile boolean NOT NULL DEFAULT false,
    meeting_url text,
    meeting_at timestamptz,
    meeting_revision integer NOT NULL DEFAULT 0,
    coach_seen bigint NOT NULL DEFAULT 0,
    student_seen bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK(student_id IS NULL OR student_id<>coach_id),
    CHECK(status<>'active' OR student_id IS NOT NULL)
);
CREATE UNIQUE INDEX coaching_active_pair ON coaching_links(coach_id,student_id) WHERE status='active';
CREATE INDEX coaching_student ON coaching_links(student_id,status);
CREATE TABLE coaching_shares (
    link_id uuid NOT NULL REFERENCES coaching_links(id) ON DELETE CASCADE,
    job_id uuid NOT NULL REFERENCES replay_jobs(id) ON DELETE CASCADE,
    report_sha256 text NOT NULL,
    reviewed_at timestamptz,
    shared_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(link_id,job_id)
);
CREATE TABLE coaching_tasks (
    id uuid PRIMARY KEY,
    link_id uuid NOT NULL REFERENCES coaching_links(id) ON DELETE CASCADE,
    title text NOT NULL,
    instruction text NOT NULL,
    criterion text NOT NULL,
    state text NOT NULL DEFAULT 'assigned' CHECK(state IN ('assigned','submitted','changes_requested','completed','archived')),
    revision integer NOT NULL DEFAULT 1,
    student_note text NOT NULL DEFAULT '',
    report_job_id uuid REFERENCES replay_jobs(id) ON DELETE SET NULL,
    report_sha256 text,
    coach_feedback text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX coaching_one_current_task ON coaching_tasks(link_id) WHERE state IN ('assigned','submitted','changes_requested');
CREATE TABLE coaching_messages (
    seq bigserial PRIMARY KEY,
    id uuid UNIQUE NOT NULL,
    link_id uuid NOT NULL REFERENCES coaching_links(id) ON DELETE CASCADE,
    author_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    body text NOT NULL,
    job_id uuid REFERENCES replay_jobs(id) ON DELETE CASCADE,
    report_sha256 text,
    evidence_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX coaching_messages_thread ON coaching_messages(link_id,seq DESC);
