-- Somewhere to keep the certainty the responses already carry.
--
-- the design put `confidence`, `degraded` and `degradations[]` on the
-- `WaterBalance` and `FrostAlert` *responses*. The tables behind them were not
-- given the same room, and the gap showed up the moment the scheduler built a
-- scheduler on top:
--
--   * `task` has `detail` and nothing else, so G recomputes the certainty on
--     every read and merges it onto the row before serialising. That works for
--     an open task and fails for a completed one, which is never regenerated —
--     its confidence is simply not recoverable afterwards. A care record that
--     cannot say how sure it was is a worse record.
--
--   * `water_balance` stores a deficit and a threshold but none of the
--     reasoning, so in live mode the API reads a number with no provenance and
--     reports a flat `medium`. The mock path, which runs the engine, is more
--     honest than the live path. That is exactly the wrong way round, and it is
--     the same shape as the bug that let four workers fail silently: the
--     truthful version was harder to see than the confident one.
--
-- Forward-only, and additive: every column is nullable or defaulted, so rows
-- written before this migration stay valid and read as "did not say".

ALTER TABLE task
    ADD COLUMN confidence   text
        CHECK (confidence IN ('high', 'medium', 'low', 'unknown')),
    ADD COLUMN degraded     boolean NOT NULL DEFAULT false,
    -- The full [{code, detail, caps_at}] list, as the API serves it. jsonb
    -- rather than a side table: it is written once with the task, read whole,
    -- and never queried by code — and a caveat the reader sees is part of the
    -- record, not a normalisation problem.
    ADD COLUMN degradations jsonb NOT NULL DEFAULT '[]'::jsonb;

-- A completed task keeps what it knew. Nothing recomputes it later, so if the
-- column is empty on a done row, the answer is "it did not say" rather than
-- "it was certain".
COMMENT ON COLUMN task.confidence IS
    'What this instruction was worth when it was issued. Never back-filled.';

ALTER TABLE water_balance
    ADD COLUMN confidence   text
        CHECK (confidence IN ('high', 'medium', 'low', 'unknown')),
    ADD COLUMN degraded     boolean NOT NULL DEFAULT false,
    ADD COLUMN degradations jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN water_balance.confidence IS
    'From workers/weather/quality.py. A modelled deficit is medium at best.';
