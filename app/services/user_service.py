
import re

from sqlalchemy.exc import IntegrityError
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

from app.database import db
from app.models import User


def normalize_email(email: str) -> str:
    """Normalize an email address for consistent account lookup."""
    return email.strip().lower()


def register_user(email: str, password: str) -> User:
    """Create a user account with a securely hashed password."""
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValueError("Email and password are required.")

    normalized_email = normalize_email(email)

    if (
        not normalized_email
        or len(normalized_email) > 255
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email)
    ):
        raise ValueError("Enter a valid email address.")

    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")

    if len(password) > 1024:
        raise ValueError("Password is too long.")

    existing_user = User.query.filter_by(email=normalized_email).first()

    if existing_user is not None:
        raise ValueError("An account with this email already exists.")

    user = User(
        email=normalized_email,
        password_hash=generate_password_hash(password),
    )

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError(
            "An account with this email already exists."
        ) from None
    except Exception:
        db.session.rollback()
        raise

    return user


def authenticate_user(email: str, password: str) -> User | None:
    """Return the user if the email and password match."""
    if not isinstance(email, str) or not isinstance(password, str):
        return None

    normalized_email = normalize_email(email)

    user = User.query.filter_by(email=normalized_email).first()

    if user is None:
        return None

    if not check_password_hash(user.password_hash, password):
        return None

    return user
