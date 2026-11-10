"""Short-lived, single-use email confirmation tokens."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from app.database import db
from app.models import EmailVerificationToken, User


TOKEN_LIFETIME = timedelta(hours=24)


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
