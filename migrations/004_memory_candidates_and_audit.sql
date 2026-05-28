-- Migration 004: 记忆候选池与审计日志（PostgreSQL）
-- 时间: 2026-04-13
-- 说明: 为候选池治理引入状态真源表 memory_candidates 与审计表 memory_audit_logs

BEGIN;

CREATE TABLE IF NOT EXISTS memory_candidates (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mem0_id VARCHAR(128),
    text TEXT NOT NULL,
    category VARCHAR(64) NOT NULL DEFAULT '',
    source VARCHAR(40) NOT NULL DEFAULT 'chat_inferred',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    evidence_ref VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    rejected_reason TEXT,
    conflict_group_id VARCHAR(64),
    fingerprint VARCHAR(64) NOT NULL DEFAULT '',
    idempotency_key VARCHAR(128) NOT NULL DEFAULT '',
    candidate_metadata JSONB,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    reviewed_at TIMESTAMP WITHOUT TIME ZONE,
    reviewed_by VARCHAR(64),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    candidate_id VARCHAR(64) NOT NULL REFERENCES memory_candidates(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor VARCHAR(64) NOT NULL DEFAULT 'system',
    action VARCHAR(32) NOT NULL,
    before_json JSONB,
    after_json JSONB,
    reason TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_user_status
    ON memory_candidates(user_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_user_created
    ON memory_candidates(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_conflict_group
    ON memory_candidates(conflict_group_id);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_fingerprint
    ON memory_candidates(fingerprint);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_idempotency_key
    ON memory_candidates(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_mem0_id
    ON memory_candidates(mem0_id);

CREATE INDEX IF NOT EXISTS idx_memory_audit_candidate_created
    ON memory_audit_logs(candidate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_audit_user_created
    ON memory_audit_logs(user_id, created_at DESC);

COMMIT;
