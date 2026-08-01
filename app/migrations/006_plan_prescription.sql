-- Planned hangboard items can carry a full capture setup, so a planned session
-- can be started on the capture page with one click.

ALTER TABLE planned_items ADD COLUMN IF NOT EXISTS prescription JSONB;
