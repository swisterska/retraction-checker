"""Application email delivery, isolated from account and worker workflows."""

from email.message import EmailMessage
import os
import smtplib
import ssl


def send_email(recipient: str, subject: str, body: str) -> None:
    """Send one plain-text message with the configured SMTP account."""
    host = os.environ.get("SMTP_HOST")
    sender = os.environ.get("MAIL_FROM")
    if not host or not sender:
        raise RuntimeError("Email is not configured (SMTP_HOST and MAIL_FROM are required).")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    timeout = 20
    if os.environ.get("SMTP_USE_SSL", "false").lower() == "true":
        with smtplib.SMTP_SSL(
            host, port, timeout=timeout, context=ssl.create_default_context(),
        ) as smtp:
            if username:
                smtp.login(username, password or "")
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        if os.environ.get("SMTP_USE_STARTTLS", "true").lower() == "true":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)


def send_verification_email(recipient: str, token: str) -> None:
    """Send a one-time link that confirms a new account's address."""
    base_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("Email is not configured (APP_PUBLIC_URL is required).")
    verification_url = f"{base_url}/verify-email?token={token}"
    send_email(
        recipient,
        "Confirm your Retraction Checker email",
        "Click the link below to confirm your email address and activate your account.\n\n"
        f"{verification_url}\n\n"
        "This link expires after 24 hours. If you did not create this account, you can ignore this email.",
    )
