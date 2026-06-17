"""backend/tests 公共 pytest 配置。"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: 需要外部服务（如 Docker Redis）的集成测试",
    )
