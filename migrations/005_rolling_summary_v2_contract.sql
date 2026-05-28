-- Migration 005: rolling summary v2 contract（PostgreSQL）
-- 时间: 2026-04-22
-- 说明:
-- 1. 补齐 sessions / session_summaries 的 rolling summary v2 字段
-- 2. 创建 summary_audit_logs 审计表
-- 3. 全部语句幂等，可重复执行

BEGIN;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS running_summary_state JSONB DEFAULT NULL;
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS running_summary_mode VARCHAR(32) DEFAULT NULL;
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_version INTEGER DEFAULT 0;

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS summary_payload JSONB DEFAULT NULL;
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS summary_mode VARCHAR(32) DEFAULT NULL;
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS summary_trigger VARCHAR(64) DEFAULT NULL;
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS compressed_message_count INTEGER DEFAULT 0;
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS total_message_count INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS summary_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    trigger VARCHAR(64),
    reason VARCHAR(128),
    source_start_message_id INTEGER,
    source_end_message_id INTEGER,
    source_start_created_at TIMESTAMP WITHOUT TIME ZONE,
    source_end_created_at TIMESTAMP WITHOUT TIME ZONE,
    input_message_count INTEGER NOT NULL DEFAULT 0,
    input_token_estimate INTEGER,
    output_summary_id INTEGER,
    output_summary_version INTEGER,
    output_summary_mode VARCHAR(32),
    audit_reasons_json JSONB,
    model_name VARCHAR(128),
    counting_mode VARCHAR(32),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_summary_audit_logs_session_created
    ON summary_audit_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summary_audit_logs_status_trigger
    ON summary_audit_logs(status, trigger);

COMMIT;
