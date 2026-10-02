-- 008 — the household's sign-in sessions and enrichment retry
-- bookkeeping on species.
--
-- household_session
--   One row per signed-in device. The cookie carries a random token; only its
--   SHA-256 is stored here, so a copy of this table signs nobody in.
--   `epoch` is derived from the operator's passphrase (an HMAC, not reversible):
--   a session whose epoch differs from the current passphrase's is invalid, so
--   rotating the `moh_household_passphrase` secret signs out every device.
--   `label` is a coarse device description ("Safari on iPhone"), capped, so the
--   Office can say which devices are signed in without storing a User-Agent.
--   A revoked or expired row is kept until the API's hourly sweep deletes rows
--   more than 30 days past either, so "signed out everywhere" can be shown
--   happening rather than inferred.
--
-- species.enrichment_*
--   The worker's hourly cron re-queues species that are pending or failed,
--   with backoff (1 h, 6 h, 24 h, then daily). `enrichment_error` is the last
--   failure in words, for the Compendium to show; it never holds a payload.
--
-- Forward-only.

CREATE TABLE household_session (
    id            uuid PRIMARY KEY,
    token_hash    bytea       NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    epoch         text        NOT NULL CHECK (length(epoch) = 16),
    label         text        NOT NULL DEFAULT 'A device' CHECK (length(label) <= 60),
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    revoked_at    timestamptz
);

-- The hot path is "is this token's session live": the unique index on
-- token_hash serves it. This one serves the Office's list and the sweep.
CREATE INDEX household_session_live_idx
    ON household_session (last_seen_at DESC)
    WHERE revoked_at IS NULL;

ALTER TABLE species
    ADD COLUMN enrichment_attempts integer NOT NULL DEFAULT 0
        CHECK (enrichment_attempts >= 0),
    ADD COLUMN enrichment_next_at  timestamptz,
    ADD COLUMN enrichment_error    text;

CREATE INDEX species_enrichment_due_idx
    ON species (enrichment_next_at NULLS FIRST)
    WHERE enrichment_state IN ('pending', 'failed', 'running');
