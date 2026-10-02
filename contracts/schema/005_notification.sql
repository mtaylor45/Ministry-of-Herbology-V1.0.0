-- 005 — the notification ledger
--
-- The hub's dedupe was derived from job_run.detail over a rolling 36
-- hours: the honest thing to build against a frozen schema, and the hub said so
-- rather than quietly adding a table. It cannot expire a key, and it cannot
-- say which destination was told without unpacking a blob.
--
-- Forward-only, like every migration here.

CREATE TABLE notification (
    id          uuid PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('rounds', 'frost', 'integration_health')),

    -- Names the DESTINATION, not the person. Two members pointing notify_prefs
    -- at one kitchen tablet are one tablet, and it should chime once — keying
    -- on the member is how a household learns to ignore the thing.
    dedupe_key  text NOT NULL,

    -- Nullable and SET NULL: the ledger outlives the member, because the
    -- question it answers is "was this destination told", not "who was told".
    member_id   uuid REFERENCES member (id) ON DELETE SET NULL,

    sent_at     timestamptz NOT NULL DEFAULT now(),

    -- The attempt, not the intent. A send refused on the way out — a credential
    -- caught by the payload guard — is exactly the event somebody will later
    -- need to find, and a ledger of successes alone cannot be asked why a phone
    -- stayed quiet.
    ok          boolean NOT NULL,
    detail      text
);

-- The lookup the dedupe actually performs: "has this key been sent recently?"
CREATE INDEX notification_dedupe_recent ON notification (dedupe_key, sent_at DESC);

-- Nothing in this table is a credential. It records THAT something was sent and
-- where to, never the body. See the design and contracts/events/mqtt.md.
