-- P6 Skill lifecycle / loader artifacts for assistant messages.
-- Additive and nullable: rollback can leave the column unused.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS skill_artifact_json JSONB DEFAULT NULL;

CREATE TABLE IF NOT EXISTS web_search_cache (
    key TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_web_search_cache_expires_at
    ON web_search_cache (expires_at);
