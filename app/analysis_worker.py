"""Run `python -m app.analysis_worker` to process queued PDF analyses."""

import json
import os
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import update

from app.database import db
from app.main import create_app
from app.models import AnalysisJob, Notification, User
from app.route_modules.documents import guest_report_payload
from app.run_grobid_pipeline import process_pdf
from app.services.analysis_jobs import guest_access_token, utcnow
from app.services.database_service import save_analysis_results
from app.services.retraction_monitor import ALERT_PREFIX, check_saved_references
from app.services.email_service import send_email


def send_ready_email(job):
    """Send a short notification using standard SMTP settings."""
    base_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "Email is not configured (APP_PUBLIC_URL is required)."
        )

    if job.guest_owner:
        token = guest_access_token(job.id)
        report_url = f"{base_url}/guest/reports/{job.id}?access={token}"
        body = (
            f"Your analysis of {job.filename} is ready.\n\n"
            f"Open your temporary report (available for 48 hours): {report_url}\n"
        )
    else:
        body = (
            f"Your analysis of {job.filename} is ready.\n\n"
            f"Sign in and open your report: {base_url}/\n"
        )
    send_email(job.email, "Your Retraction Checker report is ready", body)


def send_pending_retraction_notifications(app):
    """Send one digest email per account for newly retracted references."""
    with app.app_context():
        pending = Notification.query.filter(
            Notification.email_sent.is_(False),
            Notification.message.startswith(ALERT_PREFIX),
        ).order_by(Notification.user_id, Notification.created_at).all()
        by_user = {}
        for notification in pending:
            by_user.setdefault(notification.user_id, []).append(notification)

        sent = 0
        for user_id, notifications in by_user.items():
            user = User.query.filter_by(id=user_id).first()
            if user is None:
                app.logger.warning(
                    "Could not deliver retraction alerts: account %s was not found.",
                    user_id,
                )
                continue
            try:
                lines = "\n".join(f"• {item.message[len(ALERT_PREFIX):].strip()}" for item in notifications)
                body = (
                    "A daily check found that a reference previously marked as "
                    "verified is now listed as retracted in Retraction Watch.\n\n"
                    f"{lines}\n\nSign in to Retraction Checker to review your reports."
                )
                send_email(
                    user.email,
                    "Retraction Checker: a reference status changed",
                    body,
                )

                for notification in notifications:
                    notification.email_sent = True
                db.session.commit()
                sent += len(notifications)
            except Exception as exc:
                db.session.rollback()
                app.logger.warning(
                    "Could not send retraction alert email to account %s: %s",
                    user_id,
                    exc,
                )
        return sent
def _claim_job():
    queued = (
        AnalysisJob.query.filter_by(status="queued")
        .order_by(AnalysisJob.created_at.asc())
        .first()
    )
    if queued is None:
        return None
    result = db.session.execute(
        update(AnalysisJob)
        .where(AnalysisJob.id == queued.id, AnalysisJob.status == "queued")
        .values(status="running", updated_at=utcnow())
    )
    db.session.commit()
    if result.rowcount != 1:
        return None
    return db.session.get(AnalysisJob, queued.id)


def process_next_job(app):
    """Claim and process one queue item. Returns False when the queue is empty."""
    with app.app_context():
        job = _claim_job()
        if job is None:
            return False
        path = Path(job.pdf_path)
        try:
            references = process_pdf(str(path))
            if not references:
                raise ValueError("NO_REFERENCES_FOUND")
            if job.user_id is not None:
                job.document_id = save_analysis_results(
                    user_id=job.user_id,
                    filename=job.filename,
                    references=references,
                )
            else:
                report = guest_report_payload(job.filename, references)
                report["document"]["id"] = job.id
                report["expires_at"] = (utcnow() + timedelta(hours=48)).isoformat() + "Z"
                job.report_json = json.dumps(report)
            job.status = "completed"
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            db.session.commit()
            try:
                send_ready_email(job)
                job.email_sent = True
                job.email_error = None
                db.session.commit()
            except Exception as exc:
                app.logger.warning("Analysis %s completed; email notification failed: %s", job.id, exc)
                job.email_error = str(exc)[:255]
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(AnalysisJob, job.id)
            job.status = "failed"
            job.error_code = "NO_REFERENCES_FOUND" if str(exc) == "NO_REFERENCES_FOUND" else "ANALYSIS_FAILED"
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            db.session.commit()
            app.logger.exception("Background analysis %s failed.", job.id)
        finally:
            path.unlink(missing_ok=True)
            db.session.remove()
        return True


def purge_expired_guest_jobs(app):
    """Remove guest report data and queued PDFs after their 48-hour lifetime."""
    with app.app_context():
        cutoff = utcnow() - timedelta(hours=48)
        expired = AnalysisJob.query.filter(
            AnalysisJob.guest_owner.isnot(None),
            AnalysisJob.status.in_(["queued", "completed", "failed"]),
            AnalysisJob.created_at < cutoff,
        ).all()
        for job in expired:
            Path(job.pdf_path).unlink(missing_ok=True)
            db.session.delete(job)
        db.session.commit()
        return len(expired)


def run_worker(poll_seconds=2):
    app = create_app()
    with app.app_context():
        # This project runs one worker process; recover jobs left by its prior run.
        AnalysisJob.query.filter_by(status="running").update(
            {"status": "queued", "updated_at": utcnow()},
            synchronize_session=False,
        )
        db.session.commit()
    app.logger.info("Analysis worker started; polling every %s seconds.", poll_seconds)
    last_purge = 0.0
    last_retraction_monitor = 0.0
    while True:
        try:
            if time.monotonic() - last_purge >= 60:
                purge_expired_guest_jobs(app)
                last_purge = time.monotonic()
            if time.monotonic() - last_retraction_monitor >= 3600:
                try:
                    changed = check_saved_references(app)
                    sent = send_pending_retraction_notifications(app)
                    if changed or sent:
                        app.logger.info(
                            "Daily retraction check completed: %d new status changes, %d alerts delivered.",
                            changed,
                            sent,
                        )
                except Exception:
                    app.logger.exception("Daily retraction status check failed; it will retry later.")
                last_retraction_monitor = time.monotonic()
            if not process_next_job(app):
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            app.logger.info("Analysis worker stopped.")
            return
        except Exception:
            app.logger.exception("Analysis worker loop failed; retrying shortly.")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_worker()
