from datetime import datetime, timezone

import pytest

from app.database import db
from app.main import create_app
from app.models import (
    BackgroundTaskState,
    DetectionResult,
    ExtractedReference,
    Notification,
    User,
)
from app.services.database_service import save_analysis_results
from app.services.retraction_monitor import check_saved_references


@pytest.fixture
def monitor_app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {"users": "sqlite://"},
        "SECRET_KEY": "test-only-secret-key",
    })
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_daily_check_transitions_only_previously_verified_references(
    monitor_app, tmp_path, monkeypatch,
):
    from app.services import retraction_monitor

    csv_path = tmp_path / "retractions.csv"
    csv_path.write_text(
        "OriginalPaperDOI,Reason\n10.1000/newly-retracted,Investigation\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retraction_monitor, "ensure_retractions_dataset", lambda _path: False)
    with monitor_app.app_context():
        user = User(email="monitor@example.org", password_hash="test")
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        document_id = save_analysis_results(
            user_id=user_id,
            filename="saved-paper.pdf",
            references=[
                {
                    "title": "Newly retracted work",
                    "doi": "10.1000/newly-retracted",
                    "retracted": False,
                    "verification_status": "verified",
                },
                {
                    "title": "Previously uncertain work",
                    "doi": "10.1000/newly-retracted",
                    "retracted": False,
                    "verification_status": "not_verified",
                },
            ],
        )

    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    assert check_saved_references(monitor_app, now=now, dataset_path=str(csv_path)) == 1
    with monitor_app.app_context():
        results = DetectionResult.query.join(ExtractedReference).filter(
            ExtractedReference.document_id == document_id,
        ).order_by(DetectionResult.id).all()
        assert [result.verification_status for result in results] == ["retracted", "not_verified"]
        assert Notification.query.filter_by(user_id=user_id).count() == 1
        state = db.session.get(BackgroundTaskState, "daily_retraction_monitor")
        assert state.last_success_at is not None

    # A later daily run sees the changed status and does not alert a second time.
    assert check_saved_references(
        monitor_app,
        now=now.replace(day=4),
        dataset_path=str(csv_path),
    ) == 0
    with monitor_app.app_context():
        assert Notification.query.filter_by(user_id=user_id).count() == 1


def test_retraction_digest_marks_email_sent_and_does_not_repeat(
    monitor_app, monkeypatch,
):
    from app.analysis_worker import send_pending_retraction_notifications

    delivered = []
    monkeypatch.setattr(
        "app.analysis_worker.send_email",
        lambda recipient, subject, body: delivered.append((recipient, subject, body)),
    )
    with monitor_app.app_context():
        user = User(email="reader@example.org", password_hash="test")
        db.session.add(user)
        db.session.flush()
        notification = Notification(
            user_id=user.id,
            message="A cited reference is now retracted: “Study” in “paper.pdf” (DOI: 10.1000/example).",
        )
        db.session.add(notification)
        db.session.commit()
        notification_id = notification.id

    assert send_pending_retraction_notifications(monitor_app) == 1
    assert delivered[0][0] == "reader@example.org"
    assert "previously marked as verified" in delivered[0][2]
    assert send_pending_retraction_notifications(monitor_app) == 0
    assert len(delivered) == 1
    with monitor_app.app_context():
        assert db.session.get(Notification, notification_id).email_sent is True


def test_unconfigured_mail_keeps_retraction_alert_pending(monitor_app, monkeypatch):
    from app.analysis_worker import send_pending_retraction_notifications

    for key in ("SMTP_HOST", "MAIL_FROM"):
        monkeypatch.delenv(key, raising=False)
    with monitor_app.app_context():
        user = User(email="pending@example.org", password_hash="test")
        db.session.add(user)
        db.session.flush()
        notification = Notification(
            user_id=user.id,
            message="A cited reference is now retracted: Study (DOI: 10.1000/example).",
        )
        db.session.add(notification)
        db.session.commit()
        notification_id = notification.id

    assert send_pending_retraction_notifications(monitor_app) == 0
    with monitor_app.app_context():
        assert db.session.get(Notification, notification_id).email_sent is False
