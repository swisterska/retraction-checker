"""Short-lived, single-use email confirmation and password reset tokens."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from werkzeug.security import generate_password_hash

from app.database import db
from app.models import EmailVerificationToken, PasswordResetToken, User


TOKEN_LIFETIME = timedelta(hours=24)
PASSWORD_RESET_LIFETIME = timedelta(hours=1)


def issue_verification_token(user_id: int) -> str:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.session.query(EmailVerificationToken).filter_by(user_id=user_id).delete()
    db.session.add(EmailVerificationToken(
        user_id=user_id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + TOKEN_LIFETIME,
    ))
    db.session.commit()
    return raw_token


def confirm_email(raw_token: str) -> bool:
    if not isinstance(raw_token, str) or not raw_token:
        return False
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = EmailVerificationToken.query.filter_by(token_hash=token_hash).first()
    if record is None:
        return False

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        db.session.delete(record)
        db.session.commit()
        return False

    user = db.session.get(User, record.user_id)
    if user is None:
        db.session.delete(record)
        db.session.commit()
        return False
    user.email_verified = True
    db.session.delete(record)
    db.session.commit()
    return True


def issue_password_reset_token(user_id: int) -> str:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.session.query(PasswordResetToken).filter_by(user_id=user_id).delete()
    db.session.add(PasswordResetToken(
        user_id=user_id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + PASSWORD_RESET_LIFETIME,
    ))
    db.session.commit()
    return raw_token


def reset_password_with_token(raw_token: str, new_password: str) -> bool:
    if not isinstance(raw_token, str) or not raw_token:
        return False
    if not isinstance(new_password, str) or len(new_password) < 12 or len(new_password) > 1024:
        return False

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
    if record is None:
        return False

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        db.session.delete(record)
        db.session.commit()
        return False

    user = db.session.get(User, record.user_id)
    if user is None:
        db.session.delete(record)
        db.session.commit()
        return False

    user.password_hash = generate_password_hash(new_password)
    db.session.delete(record)
    db.session.commit()
    return True
