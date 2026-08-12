from __future__ import annotations

import tests.conftest as test_config


def test_explicit_test_database_environment_wins(monkeypatch) -> None:
    explicit = "postgresql://explicit.invalid/isolated_test"
    monkeypatch.setenv(test_config._TEST_DATABASE_URL, explicit)

    def fail_if_dotenv_is_read(*_args, **_kwargs):
        raise AssertionError("显式进程环境存在时不应读取 .env")

    monkeypatch.setattr(test_config, "dotenv_values", fail_if_dotenv_is_read)

    test_config._load_local_test_database_url()

    assert test_config.os.environ[test_config._TEST_DATABASE_URL] == explicit


def test_local_test_database_url_encodes_password(monkeypatch) -> None:
    monkeypatch.delenv(test_config._TEST_DATABASE_URL, raising=False)
    monkeypatch.setattr(
        test_config,
        "dotenv_values",
        lambda *_args, **_kwargs: {
            test_config._TEST_DATABASE_URL: (
                "postgresql://venagent:${POSTGRES_PASSWORD}"
                "@127.0.0.1:5432/venagent_test"
            ),
            test_config._POSTGRES_PASSWORD: "pa:ss/@?",
        },
    )

    test_config._load_local_test_database_url()

    assert test_config.os.environ[test_config._TEST_DATABASE_URL] == (
        "postgresql://venagent:pa%3Ass%2F%40%3F@127.0.0.1:5432/venagent_test"
    )


def test_unresolved_test_database_password_does_not_enable_test(monkeypatch) -> None:
    monkeypatch.delenv(test_config._TEST_DATABASE_URL, raising=False)
    monkeypatch.setattr(
        test_config,
        "dotenv_values",
        lambda *_args, **_kwargs: {
            test_config._TEST_DATABASE_URL: (
                "postgresql://venagent:${POSTGRES_PASSWORD}"
                "@127.0.0.1:5432/venagent_test"
            )
        },
    )

    test_config._load_local_test_database_url()

    assert test_config._TEST_DATABASE_URL not in test_config.os.environ
