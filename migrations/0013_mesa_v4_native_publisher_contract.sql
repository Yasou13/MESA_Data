-- Native MESA V4 delivery contract: session routes and durable session identity.
-- Forward-only and safe for existing data roots.

ALTER TABLE mesa_target_settings ADD COLUMN session_start_path TEXT NOT NULL DEFAULT '/v4/sessions/start';
ALTER TABLE mesa_target_settings ADD COLUMN session_end_path_template TEXT NOT NULL DEFAULT '/v4/sessions/{session_id}/end';
ALTER TABLE mesa_deliveries ADD COLUMN remote_session_id TEXT;

-- Existing stored route assumptions were deliberately marked unknown by 0008.
-- New defaults make the authoritative V4 routes available once an operator
-- explicitly configures/verifies the rest of the target contract.
