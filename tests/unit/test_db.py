from app.db import _prepare_async_url


def test_converts_postgresql_to_asyncpg():
    url, connect_args = _prepare_async_url("postgresql://user:pass@localhost/db")
    assert url.startswith("postgresql+asyncpg://")
    assert connect_args == {}


def test_sslmode_disable_sets_ssl_false():
    url, connect_args = _prepare_async_url(
        "postgresql://user:pass@localhost/db?sslmode=disable"
    )
    assert connect_args.get("ssl") is False
    assert "sslmode" not in url


def test_other_sslmode_is_stripped_without_ssl_arg():
    url, connect_args = _prepare_async_url(
        "postgresql://user:pass@localhost/db?sslmode=require"
    )
    assert "ssl" not in connect_args
    assert "sslmode" not in url


def test_no_sslmode_returns_empty_connect_args():
    url, connect_args = _prepare_async_url("postgresql://user:pass@localhost/db")
    assert connect_args == {}
    assert "sslmode" not in url


def test_already_asyncpg_url_is_unchanged():
    url, connect_args = _prepare_async_url(
        "postgresql+asyncpg://user:pass@localhost/db"
    )
    assert url == "postgresql+asyncpg://user:pass@localhost/db"
    assert connect_args == {}
