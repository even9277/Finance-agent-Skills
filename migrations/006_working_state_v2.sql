-- Working State v2: additive, backward-compatible migration.

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS working_state JSONB;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS working_state_version INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS working_state_updated_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS working_state_events (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id BIGINT,
    field_name VARCHAR(32) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    source VARCHAR(32) NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 0,
    summary_version INTEGER DEFAULT 0,
    state_version INTEGER NOT NULL,
    trace_id VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ws_events_session_created
    ON working_state_events(session_id, created_at);
