import smtplib
import pytest
from app import email_verification as mail, config
from app.errors import AccountError


@pytest.mark.parametrize('fail_quit', [False, True])
def test_delivery_uses_tls_and_accepts_success_before_quit(monkeypatch, fail_quit):
    sent = []
    monkeypatch.setattr(config, 'SMTP_SSL', True)
    monkeypatch.setattr(config, 'SMTP_FROM', 'sender@example.com')
    class SMTP:
        def __init__(self, host, port, timeout, context):
            assert timeout == 15 and context.check_hostname
        def __enter__(self): return self
        def __exit__(self, *args):
            if fail_quit: raise smtplib.SMTPServerDisconnected('test')
        def login(self, *args): pass
        def send_message(self, message):
            sent.append(message)
            return {}
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL', SMTP)
    mail.send_email('recipient@example.com', 'http://localhost:8000/verify-email#token=test')
    assert sent[0]['To'] == 'recipient@example.com'
    assert 'Message-ID' in sent[0]


def test_delivery_sanitizes_authentication_error(monkeypatch):
    monkeypatch.setattr(config, 'SMTP_FROM', 'sender@example.com')
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b'private server detail')
    monkeypatch.setattr(mail.smtplib, 'SMTP_SSL', fail)
    with pytest.raises(AccountError) as caught:
        mail.send_email('recipient@example.com', 'http://localhost:8000/verify-email#token=test')
    assert caught.value.code == 'EMAIL_SEND_FAILED'
    assert 'private' not in str(caught.value)
