-- P5 Plan-and-Execute artifacts for assistant messages.
-- Additive and nullable: existing rows remain compatible.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS plan_artifact_json JSONB DEFAULT NULL;

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS verification_json JSONB DEFAULT NULL;

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS allowed_claim_level VARCHAR(20) DEFAULT NULL;
