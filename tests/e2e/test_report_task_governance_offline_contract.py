"""锁定 D06 离线 Compose 必须提供的双实例测试拓扑。"""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.e2e
def test_offline_compose_declares_isolated_second_backend_and_d06_gates() -> None:
    """D06-T08：离线栈必须能把同一任务请求分发到两个真实后端实例。"""
    compose = (PROJECT_ROOT / "docker/docker-compose.offline.yml").read_text(encoding="utf-8")
    nginx = (PROJECT_ROOT / "docker/nginx/offline.conf").read_text(encoding="utf-8")

    assert "backend-secondary:" in compose
    assert "RUN_D06_ISOLATED_INFRA_TESTS" in compose
    assert 'ENABLE_REPORT_TASK_GOVERNANCE: "true"' in compose
    assert 'ENABLE_REPORT_TASK_REDIS: "true"' in compose
    assert "REPORT_TASK_REDIS_NAMESPACE: finance-report-offline-e2e" in compose
    assert "postgresql+asyncpg://e2e:e2e@postgres-e2e:5432/e2e" in compose
    assert "redis://redis-e2e:6379" in compose
    assert "tmpfs:" in compose
    assert "internal: true" in compose
    assert "./nginx/offline.conf:/etc/nginx/conf.d/default.conf:ro" in compose
    assert "server backend:8000;" in nginx
    assert "server backend-secondary:8000;" in nginx
    assert "proxy_buffering off;" in nginx
