"""Short-lived, single-use email confirmation and password reset tokens."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from werkzeug.security import generate_password_hash

from app.database import db
from app.models import AnalysisJob, EmailVerificationToken, PasswordResetToken, User
from app.services.database_service import save_analysis_results


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
    claim_guest_reports_for_user(user)
    return True


def claim_guest_reports_for_user(user) -> int:
    """Move recent guest reports into an account after email ownership is proven."""
    # Guest reports are attached only after the address is verified, which
    # proves ownership of the email used for those temporary checks.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    guest_job_ids = [job_id for (job_id,) in AnalysisJob.query.with_entities(AnalysisJob.id).filter_by(
        email=user.email,
        status="completed",
    ).filter(
        AnalysisJob.guest_owner.isnot(None),
        AnalysisJob.user_id.is_(None),
        AnalysisJob.report_json.isnot(None),
        AnalysisJob.created_at >= cutoff,
    ).all()]
    claimed = 0
    for job_id in guest_job_ids:
        try:
            claim = db.session.execute(
                update(AnalysisJob)
                .where(
                    AnalysisJob.id == job_id,
                    AnalysisJob.email == user.email,
                    AnalysisJob.guest_owner.isnot(None),
                    AnalysisJob.user_id.is_(None),
                    AnalysisJob.status == "completed",
                )
                .values(user_id=user.id, guest_owner=None)
            )
            if claim.rowcount != 1:
                db.session.rollback()
                continue
            db.session.expire_all()
            job = db.session.get(AnalysisJob, job_id)
            if job is None or not job.report_json:
                db.session.rollback()
                continue
            report = json.loads(job.report_json)
            references = [
                {
                    "title": item.get("title"),
                    "authors": item.get("authors"),
                    "year": item.get("year"),
                    "doi": item.get("doi"),
                    "pmid": item.get("pmid"),
                    "retracted": item.get("is_retracted", False),
                    "verification_status": item.get("verification_status"),
                    "verification_note": item.get("verification_note"),
                    "retraction_reason": (item.get("retracted_publication") or {}).get("retraction_reason"),
                }
                for item in report.get("results", [])
            ]
            job.document_id = save_analysis_results(
                user_id=user.id,
                filename=job.filename,
                references=references,
                upload_date=job.finished_at or job.created_at,
                last_checked_at=job.finished_at or job.created_at,
                commit=False,
            )
            job.report_json = None
            db.session.commit()
            claimed += 1
        except Exception:
            db.session.rollback()
    return claimed


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
