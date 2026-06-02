-- Trace observability tables (observation-only; no business table changes).
-- Apply on PostgreSQL; SQLite dev uses trace_db_sink.ensure_tables() equivalent DDL.

CREATE TABLE IF NOT EXISTS trace_sessions (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    meta_json JSONB DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS trace_spans (
    id BIGSERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    session_id TEXT,
    span_id TEXT,
    parent_span_id TEXT,
    stage_name TEXT,
    status TEXT,
    started_at TIMESTAMP WITHOUT TIME ZONE,
    ended_at TIMESTAMP WITHOUT TIME ZONE,
    duration_ms DOUBLE PRECISION,
    data_json JSONB DEFAULT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trace_spans_session_created
    ON trace_spans (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_id
    ON trace_spans (trace_id);

CREATE INDEX IF NOT EXISTS idx_trace_spans_stage_created
    ON trace_spans (stage_name, created_at DESC);
