from unittest.mock import patch

import pytest

from app.services.email_service import EmailDeliveryError, send_alert_email


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = False
        self.sent = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        return None

    def starttls(self, *, context):
        self.started_tls = context is not None

    def login(self, username, password):
        self.logged_in = (username, password)

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)
        return {}


@pytest.fixture(autouse=True)
def smtp_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "email_smtp_port", 587)
    monkeypatch.setattr(settings, "email_smtp_user", "sender@example.test")
    monkeypatch.setattr(settings, "email_smtp_pass", "app-password")
    monkeypatch.setattr(settings, "email_smtp_from", "DataLens <sender@example.test>")
    monkeypatch.setattr(settings, "email_smtp_timeout_seconds", 7)
    monkeypatch.setattr(settings, "email_smtp_use_ssl", False)
    monkeypatch.setattr(settings, "email_smtp_use_starttls", True)
    FakeSMTP.instances.clear()


def test_send_alert_email_uses_starttls_and_reports_delivery():
    with patch("app.services.email_service.smtplib.SMTP", FakeSMTP):
        send_alert_email(
            to=["recipient@example.test"],
            subject="Test",
            body_html="<p>Hello</p>",
        )

    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.test"
    assert smtp.timeout == 7
    assert smtp.started_tls is True
    assert smtp.logged_in == ("sender@example.test", "app-password")
    assert smtp.sent[1] == ["recipient@example.test"]
    assert "Subject: Test" in smtp.sent[2]


def test_send_alert_email_raises_for_refused_recipients():
    class RefusingSMTP(FakeSMTP):
        def sendmail(self, sender, recipients, message):
            return {recipients[0]: (550, b"mailbox unavailable")}

    with patch("app.services.email_service.smtplib.SMTP", RefusingSMTP):
        with pytest.raises(EmailDeliveryError, match="SMTP rejected recipient"):
            send_alert_email(
                to=["recipient@example.test"],
                subject="Test",
                body_html="<p>Hello</p>",
            )


def test_send_alert_email_rejects_missing_smtp_configuration(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "email_smtp_pass", "")
    with pytest.raises(EmailDeliveryError, match="SMTP is not configured"):
        send_alert_email(
            to=["recipient@example.test"],
            subject="Test",
            body_html="<p>Hello</p>",
        )
