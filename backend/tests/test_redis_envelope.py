from backend.integrations.redis.envelope import CacheEnvelope


def test_envelope_should_serialize_and_deserialize():
    env = CacheEnvelope(
        data={"foo": "bar"},
        schema_version=1,
        payload_version=3,
        source="demo",
    )
    payload = env.dict() if hasattr(env, "dict") else env.model_dump()
    restored = CacheEnvelope(**payload)
    assert restored.data == {"foo": "bar"}
    assert restored.schema_version == 1
    assert restored.payload_version == 3
    assert restored.source == "demo"
    assert restored.updated_at


def test_envelope_should_allow_optional_payload_version():
    env = CacheEnvelope(data={"ok": True}, source="demo")
    assert env.payload_version is None


def test_envelope_should_fail_when_required_field_missing():
    try:
        CacheEnvelope(data={"x": 1})
        assert False, "expected validation error when source is missing"
    except Exception:
        pass

