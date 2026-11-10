import pytest

from app.services import email_service


def test_smtp_sender_uses_starttls_and_authentication(monkeypatch):
    messages = []
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, **_kwargs):
            calls.append("starttls")

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            messages.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.org")
    monkeypatch.setenv("SMTP_PASSWORD", "test-secret")
    monkeypatch.setenv("SMTP_USE_SSL", "false")
    monkeypatch.setenv("SMTP_USE_STARTTLS", "true")
    monkeypatch.setenv("MAIL_FROM", "sender@example.org")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    email_service.send_email("reader@example.org", "Subject", "Body")

    assert calls[0] == ("smtp.example.org", 587, 20)
    assert "starttls" in calls
    assert ("login", "sender@example.org", "test-secret") in calls
    assert messages[0]["To"] == "reader@example.org"
    assert messages[0].get_content() == "Body\n"


def test_smtp_sender_requires_host_and_from_address(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("MAIL_FROM", raising=False)
    with pytest.raises(RuntimeError, match="SMTP_HOST and MAIL_FROM"):
        email_service.send_email("reader@example.org", "Subject", "Body")


def test_verification_email_uses_public_confirmation_link(monkeypatch):
    captured = []
    monkeypatch.setenv("APP_PUBLIC_URL", "https://checker.example.org/")
    monkeypatch.setattr(
        email_service,
        "send_email",
        lambda *args: captured.append(args),
    )

    email_service.send_verification_email("reader@example.org", "one-time-token")

    assert captured[0][0] == "reader@example.org"
    assert "https://checker.example.org/verify-email?token=one-time-token" in captured[0][2]
