import pytest

from app import account_store, config


class Stop(Exception):
    pass


def captured_kwargs(monkeypatch):
    seen = {}

    def fake_connect(**kwargs):
        seen.update(kwargs)
        raise account_store.pymysql.err.OperationalError(2003, "stop")

    monkeypatch.setattr(account_store.pymysql, "connect", fake_connect)
    with pytest.raises(account_store.AccountError):
        with account_store._cursor():
            pass
    return seen


def test_no_tls_options_without_ca(monkeypatch):
    monkeypatch.setattr(config, "MYSQL_SSL_CA", None)
    kwargs = captured_kwargs(monkeypatch)
    assert "ssl" not in kwargs and "ssl_ca" not in kwargs


def test_ca_enables_certificate_verification(monkeypatch):
    monkeypatch.setattr(config, "MYSQL_SSL_CA", "/run/secrets/mysql-ca.pem")
    kwargs = captured_kwargs(monkeypatch)
    assert kwargs["ssl_ca"] == "/run/secrets/mysql-ca.pem"
    assert kwargs["ssl_verify_cert"] is True
    assert kwargs["ssl_verify_identity"] is False
