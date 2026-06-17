from backend.integrations.redis.key_builder import KeyBuilder


def test_key_builder_should_generate_all_expected_keys():
    builder = KeyBuilder("dev")
    assert builder.stm_state("u1", "s1") == "finagent:dev:stm:state:u1:s1"
    assert builder.stm_tail("u1", "s1") == "finagent:dev:stm:tail:u1:s1"
    assert builder.stm_summary("u1", "s1") == "finagent:dev:stm:summary:u1:s1"
    assert (
        builder.report_idempotency("u1", "600519.SH", "hash1")
        == "finagent:dev:report:idempotency:u1:600519.SH:hash1"
    )
    assert (
        builder.report_idempotency_by_user_query("u1", "hash1")
        == "finagent:dev:report:idempotency:u1:hash1"
    )
    assert builder.report_status("task-1") == "finagent:dev:report:status:task-1"
    assert builder.lock("regen") == "finagent:dev:lock:regen"
    assert builder.demo("hello") == "finagent:dev:demo:item:hello"


def test_key_builder_should_use_different_env_prefix():
    assert KeyBuilder("prod").demo("x") == "finagent:prod:demo:item:x"


def test_key_builder_should_raise_when_env_or_parts_are_empty():
    try:
        KeyBuilder("")
        assert False, "expected ValueError for empty env"
    except ValueError:
        pass

    builder = KeyBuilder("dev")
    try:
        builder.demo("")
        assert False, "expected ValueError for empty item id"
    except ValueError:
        pass
