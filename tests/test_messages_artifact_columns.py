from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_message_model_declares_plan_verification_columns():
    text = (ROOT / "backend/db/models.py").read_text(encoding="utf-8")
    assert "plan_artifact_json" in text
    assert "skill_artifact_json" in text
    assert "verification_json" in text
    assert "allowed_claim_level" in text
    assert "Mapped[dict | None]" in text
    assert "String(20)" in text


def test_startup_migration_mentions_plan_artifact_columns():
    text = (ROOT / "backend/db/database.py").read_text(encoding="utf-8")
    assert "plan_artifact_json" in text
    assert "skill_artifact_json" in text
    assert "verification_json" in text
    assert "allowed_claim_level" in text


def test_postgres_migration_is_additive_and_nullable():
    text = (ROOT / "migrations/007_plan_verification_artifacts.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS plan_artifact_json" in text
    assert "ADD COLUMN IF NOT EXISTS verification_json" in text
    assert "ADD COLUMN IF NOT EXISTS allowed_claim_level" in text
    assert "DEFAULT NULL" in text


def test_skill_lifecycle_migration_is_additive_and_nullable():
    text = (ROOT / "migrations/008_skill_lifecycle.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS skill_artifact_json" in text
    assert "DEFAULT NULL" in text
