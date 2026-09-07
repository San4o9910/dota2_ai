-- Offline evidence exchange only. These tables never authorize paid inference.
CREATE TABLE hermes_exports (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL REFERENCES portal_accounts(owner_id) ON DELETE CASCADE,
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot)='object' AND octet_length(snapshot::text)<=393216),
    source_jobs jsonb NOT NULL CHECK (jsonb_typeof(source_jobs)='object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(id,owner_id)
);
CREATE INDEX hermes_exports_owner_created ON hermes_exports(owner_id,created_at DESC);
CREATE TABLE hermes_reviews (
    id uuid PRIMARY KEY,
    export_id uuid NOT NULL UNIQUE,
    owner_id text NOT NULL,
    review_sha256 text NOT NULL CHECK (review_sha256 ~ '^[0-9a-f]{64}$'),
    review jsonb NOT NULL CHECK (jsonb_typeof(review)='object' AND octet_length(review::text)<=32768),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(export_id,owner_id) REFERENCES hermes_exports(id,owner_id) ON DELETE CASCADE
);
CREATE INDEX hermes_reviews_owner_created ON hermes_reviews(owner_id,created_at DESC);
