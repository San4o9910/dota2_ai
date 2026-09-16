-- Separate from the legacy D1 scaffold. Money is integer kopecks, never floats.
CREATE TABLE portal_orders (
 id uuid PRIMARY KEY,
 owner_id text REFERENCES portal_accounts(owner_id) ON DELETE SET NULL,
 mode text NOT NULL CHECK(mode IN ('test','live')),
 shop_id text NOT NULL,
 product text NOT NULL CHECK(product IN ('single','five')),
 units integer NOT NULL CHECK(units IN (1,5)),
 amount integer NOT NULL CHECK(amount>0),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','succeeded','canceled')),
 payment_id text UNIQUE,
 checkout_url text,
 request_payload jsonb NOT NULL,
 terms_version text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX portal_orders_owner ON portal_orders(owner_id,created_at DESC);
CREATE TABLE portal_credit_uses (
 id uuid PRIMARY KEY,
 job_id uuid UNIQUE REFERENCES replay_jobs(id) ON DELETE SET NULL,
 order_id uuid NOT NULL REFERENCES portal_orders(id) ON DELETE RESTRICT,
 state text NOT NULL CHECK(state IN ('held','consumed','released')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE portal_refunds (
 id uuid PRIMARY KEY,
 order_id uuid NOT NULL UNIQUE REFERENCES portal_orders(id) ON DELETE RESTRICT,
 units integer NOT NULL CHECK(units>0),
 amount integer NOT NULL CHECK(amount>0),
 reason text NOT NULL CHECK(length(reason) BETWEEN 5 AND 1500),
 status text NOT NULL DEFAULT 'requested' CHECK(status IN ('requested','pending','succeeded','canceled')),
 provider_id text UNIQUE,
 request_payload jsonb,
 submitted_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- Keep commercial history when an account is deleted; ownership is anonymized.
CREATE FUNCTION settle_portal_credit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.state IN ('ready','failed','deleted') AND EXISTS(SELECT 1 FROM portal_credit_uses WHERE job_id=NEW.id AND state='held') THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.owner_id,2));
  UPDATE portal_credit_uses SET state=CASE WHEN NEW.state='ready' AND NEW.result_payload#>>'{coaching,status}'='ready'
    THEN 'consumed' ELSE 'released' END,updated_at=now() WHERE job_id=NEW.id AND state='held';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER settle_portal_credit_on_result AFTER UPDATE OF state ON replay_jobs
 FOR EACH ROW EXECUTE FUNCTION settle_portal_credit();

CREATE FUNCTION release_deleted_portal_credit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(OLD.owner_id,2));
 UPDATE portal_credit_uses SET state='released',updated_at=now() WHERE job_id=OLD.id AND state='held';
 RETURN OLD;
END $$;
CREATE TRIGGER release_deleted_portal_credit BEFORE DELETE ON replay_jobs
 FOR EACH ROW EXECUTE FUNCTION release_deleted_portal_credit();
