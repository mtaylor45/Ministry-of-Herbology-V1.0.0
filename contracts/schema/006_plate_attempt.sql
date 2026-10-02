-- 006 — a sourcing attempt is a fact, whether or not it produced a plate.
--
-- the design. `plate` holds plates that exist and nothing about attempts that
-- produced none, so a live deployment could not tell "every catalogue was asked
-- and none had it" from "the worker has never run", and `GET /journal/coverage`
-- (contract 1.6.0, the design) answered `not_run` for four of its six reason
-- kinds. This table is where `workers.plates.pipeline.PlateOutcome` goes.
--
-- One row per run per plant. The latest row per specimen is what coverage
-- reads; older rows are history and may be pruned by an operator.
-- Forward-only, like every migration here.

CREATE TABLE plate_attempt (
    id              uuid PRIMARY KEY,
    specimen_id     uuid REFERENCES specimen(id) ON DELETE CASCADE,
    species_id      uuid REFERENCES species(id) ON DELETE CASCADE,
    -- The pipeline's own vocabulary (`workers.plates.pipeline.OUTCOME_KINDS`)
    -- plus the one case a run cannot report about itself. `sourced` and
    -- `generated` produced `plate_id`; the rest did not.
    outcome         text NOT NULL CHECK (outcome IN (
                        'sourced', 'generated', 'no_candidate',
                        'unlicensed_candidate', 'generation_unavailable',
                        'unusable_image', 'store_unavailable')),
    plate_id        uuid REFERENCES plate(id) ON DELETE SET NULL,
    -- The sentence the pipeline wrote, shown to the reader as-is.
    reason          text,
    -- Every candidate looked at and refused, with why; sources not asked and
    -- why not. Arrays of strings; kept so the coverage report can say
    -- "Commons had one and its licence was CC BY-NC" rather than "not found".
    rejections      jsonb NOT NULL DEFAULT '[]'::jsonb,
    skipped_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    ran_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (specimen_id IS NOT NULL OR species_id IS NOT NULL),
    CHECK ((outcome IN ('sourced', 'generated')) = (plate_id IS NOT NULL))
);

CREATE INDEX plate_attempt_specimen_latest_idx ON plate_attempt (specimen_id, ran_at DESC);
CREATE INDEX plate_attempt_species_latest_idx ON plate_attempt (species_id, ran_at DESC);
