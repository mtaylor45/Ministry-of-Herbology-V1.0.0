-- 007 — what a feed's calendar push last did.
--
-- `calendar_feed.push_config` has existed and held nothing. the design
-- §2 decides the CalDAV credential is never stored by the app — it is the
-- operator's swarm secret `moh_caldav_<feed_id>`, read at push time — so
-- `push_config` must never hold a URL, a username or a password. This migration
-- adds what the app *does* need to keep, none of which is secret:
--
--   push_state the adapter's per-UID memory, `{uid: {sequence, etag}}`
--                   (workers.hub.calendar.PushResult.state). Lets a repeat push
--                   cost no request; dropping it is always safe, only slower.
--   push_dirty_since when this feed's content last changed without a push
--                   having caught up. Null when nothing is owed. G sets it on
--                   any change that alters a pushing feed's events and clears it
--                   on a push that reports ok; the five-minute bound is measured
--                   from it.
--   push_last_ok_at when a push last finished with nothing failed or refused.
--   push_error the last failure as an operator-readable sentence, already
--                   redacted by the adapter and passed through
--                   workers.hub.credentials before it is stored.
--
-- `push_status` is not a column: it is derived (off when push_target is none;
-- awaiting_operator when the secret file is absent; failing when push_error is
-- set and newer than push_last_ok_at; ok otherwise), so it cannot disagree with
-- the facts it is made from — the rule the design set for Integration.status.
-- Forward-only.

ALTER TABLE calendar_feed
    ADD COLUMN push_state       jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN push_dirty_since timestamptz,
    ADD COLUMN push_last_ok_at  timestamptz,
    ADD COLUMN push_error       text;

-- The sweep reads feeds that owe a push; keep it a short index scan.
CREATE INDEX calendar_feed_push_owed_idx
    ON calendar_feed (push_dirty_since)
    WHERE push_dirty_since IS NOT NULL AND revoked_at IS NULL;
