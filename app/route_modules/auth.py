
import hmac
import re
import secrets

from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.main import limiter

from app.database import db
from app.models import (
    AnalysisJob,
    DetectionResult,
    DocumentWatch,
    EmailVerificationToken,
    ExtractedReference,
    Notification,
    PasswordResetToken,
    UploadedDocument,
    User,
)
from app.services.email_service import send_password_reset_email, send_verification_email
from app.services.email_verification import (
    claim_guest_reports_for_user,
    confirm_email,
    issue_password_reset_token,
    issue_verification_token,
    reset_password_with_token,
)
from app.services.user_service import (
    register_user,
    authenticate_user,
    normalize_email,
)
from app.route_modules.helpers import (
    current_user_id,
    authentication_required,
    login_required,
)


def csrf_error():
    """Return a standard JSON response for invalid CSRF tokens."""
    return jsonify({
        "status": "error",
        "message": "Missing or invalid CSRF token. Fetch a new token and retry.",
    }), 400


def protect_csrf():
    """Validate CSRF tokens on state-changing requests."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    expected = session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token")

    if (
        not isinstance(expected, str)
        or not isinstance(supplied, str)
        or not hmac.compare_digest(expected, supplied)
    ):
        return csrf_error()

    return None


def clear_user_history(user):
    """Delete a user's uploaded documents and all related history."""
    documents = UploadedDocument.query.filter_by(user_id=user.id).all()
    document_ids = [document.id for document in documents]

    reference_ids = []
    if document_ids:
        reference_ids = [
            reference.id
            for reference in ExtractedReference.query.filter(
                ExtractedReference.document_id.in_(document_ids)
            ).all()
        ]

    if reference_ids:
        db.session.query(DetectionResult).filter(
            DetectionResult.reference_id.in_(reference_ids)
        ).delete(synchronize_session=False)

    if document_ids:
        db.session.query(ExtractedReference).filter(
            ExtractedReference.document_id.in_(document_ids)
        ).delete(synchronize_session=False)

    db.session.query(Notification).filter_by(user_id=user.id).delete(
        synchronize_session=False,
    )
    db.session.query(DocumentWatch).filter_by(user_id=user.id).delete(
        synchronize_session=False,
    )
    db.session.query(AnalysisJob).filter_by(user_id=user.id).delete(
        synchronize_session=False,
    )
    db.session.query(EmailVerificationToken).filter_by(user_id=user.id).delete(
        synchronize_session=False,
    )
    db.session.query(PasswordResetToken).filter_by(user_id=user.id).delete(
        synchronize_session=False,
    )

    for document in UploadedDocument.query.filter_by(user_id=user.id).all():
        db.session.delete(document)

    db.session.commit()


def register_auth_routes(app):
    """Register authentication-related routes."""

    app.before_request(protect_csrf)

    @app.route("/api/csrf", methods=["GET"])
    def get_csrf_token():
        token = session.get("csrf_token")

        if not isinstance(token, str):
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token

        return jsonify({
            "status": "success",
            "csrf_token": token,
        }), 200

    @app.route("/api/register", methods=["POST"])
    @limiter.limit("5 per hour")
    def register():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        email = data.get("email")
        password = data.get("password")

        if not isinstance(email, str) or not isinstance(password, str):
            return jsonify({
                "status": "error",
                "message": "Email and password are required.",
            }), 400

        try:
            user = register_user(email, password)
        except ValueError as error:
            return jsonify({
                "status": "error",
                "message": str(error),
            }), 400

        token = issue_verification_token(user.id)
        try:
            send_verification_email(user.email, token)
        except Exception:
            app.logger.exception(
                "Account %s was created but its verification email could not be sent.",
                user.id,
            )
            return jsonify({
                "status": "error",
                "code": "VERIFICATION_EMAIL_FAILED",
                "message": (
                    "Your account is saved but not active yet. We could not send "
                    "the confirmation email. Try again after email delivery is configured."
                ),
            }), 503

        return jsonify({
            "status": "pending_verification",
            "message": "Check your email and click the confirmation link to activate your account.",
        }), 201

    @app.route("/api/verify-email", methods=["POST"])
    @limiter.limit("10 per hour")
    def verify_email():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        if not confirm_email(token):
            return jsonify({
                "status": "error",
                "code": "INVALID_VERIFICATION_LINK",
                "message": "This confirmation link is invalid or has expired. Request a new one.",
            }), 400
        return jsonify({
            "status": "success",
            "message": "Email confirmed. You can now sign in.",
        }), 200

    @app.route("/api/forgot-password", methods=["POST"])
    @limiter.limit("5 per hour")
    def forgot_password():
        data = request.get_json(silent=True)
        email = data.get("email") if isinstance(data, dict) else None
        if not isinstance(email, str):
            return jsonify({
                "status": "error",
                "message": "Enter your email address.",
            }), 400

        normalized_email = normalize_email(email)
        user = User.query.filter_by(email=normalized_email).first()
        if user is not None:
            token = issue_password_reset_token(user.id)
            try:
                send_password_reset_email(user.email, token)
            except Exception:
                app.logger.exception(
                    "Could not send password reset email to account %s.",
                    user.id,
                )
                return jsonify({
                    "status": "error",
                    "code": "PASSWORD_RESET_EMAIL_FAILED",
                    "message": "We could not send the reset email right now. Please try again later.",
                }), 503

        return jsonify({
            "status": "success",
            "message": "If an account with that email exists, a password reset link has been sent.",
        }), 200

    @app.route("/api/reset-password", methods=["POST"])
    @limiter.limit("10 per hour")
    def reset_password():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        token = data.get("token")
        password = data.get("password")

        if not isinstance(token, str) or not isinstance(password, str):
            return jsonify({
                "status": "error",
                "message": "A valid reset token and a new password are required.",
            }), 400

        if len(password) < 12 or len(password) > 1024:
            return jsonify({
                "status": "error",
                "message": "Password must contain at least 12 characters.",
            }), 400

        if not reset_password_with_token(token, password):
            return jsonify({
                "status": "error",
                "code": "INVALID_RESET_TOKEN",
                "message": "This reset link is invalid or has expired. Request a new one.",
            }), 400

        return jsonify({
            "status": "success",
            "message": "Your password has been reset successfully.",
        }), 200

    @app.route("/api/resend-verification", methods=["POST"])
    @limiter.limit("5 per hour")
    def resend_verification():
        data = request.get_json(silent=True)
        email = data.get("email") if isinstance(data, dict) else None
        if not isinstance(email, str):
            return jsonify({
                "status": "error",
                "message": "Enter your email address.",
            }), 400
        user = User.query.filter_by(email=email.strip().lower()).first()
        if user is None or user.email_verified:
            return jsonify({
                "status": "success",
                "message": "If the account needs confirmation, a new link will be sent.",
            }), 200
        token = issue_verification_token(user.id)
        try:
            send_verification_email(user.email, token)
        except Exception:
            app.logger.exception(
                "Could not resend an email verification link for account %s.",
                user.id,
            )
            return jsonify({
                "status": "error",
                "code": "VERIFICATION_EMAIL_FAILED",
                "message": "The confirmation email could not be sent. Try again later.",
            }), 503
        return jsonify({
            "status": "success",
            "message": "If the account needs confirmation, a new link will be sent.",
        }), 200

    @app.route("/api/login", methods=["POST"])
    @limiter.limit("5 per minute")
    def login():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        email = data.get("email")
        password = data.get("password")

        if not isinstance(email, str) or not isinstance(password, str):
            return jsonify({
                "status": "error",
                "message": "Email and password are required.",
            }), 400

        user = authenticate_user(email, password)

        if user is None:
            return jsonify({
                "status": "error",
                "message": "Invalid email or password.",
            }), 401

        if not user.email_verified:
            return jsonify({
                "status": "error",
                "code": "EMAIL_NOT_VERIFIED",
                "message": "Verify your email before signing in. You can request a new confirmation link below.",
            }), 403

        claim_guest_reports_for_user(user)

        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(32)

        return jsonify({
            "status": "success",
            "message": "Logged in successfully.",
            "csrf_token": session["csrf_token"],
            "user": {
                "id": user.id,
                "email": user.email,
            },
        }), 200

    @app.route("/api/logout", methods=["POST"])
    @login_required
    def logout():
        session.clear()

        return jsonify({
            "status": "success",
            "message": "Logged out successfully.",
        }), 200

    @app.route("/api/me", methods=["GET"])
    @login_required
    def get_current_user():
        user = db.session.get(User, current_user_id())

        if user is None:
            session.clear()
            return authentication_required()

        return jsonify({
            "status": "success",
            "user": {
                "id": user.id,
                "email": user.email,
            },
        }), 200

    @app.route("/api/account", methods=["GET"])
    @login_required
    def get_account_details():
        user = db.session.get(User, current_user_id())
        if user is None:
            session.clear()
            return authentication_required()

        return jsonify({
            "status": "success",
            "user": {
                "id": user.id,
                "email": user.email,
                "email_verified": user.email_verified,
            },
        }), 200

    @app.route("/api/account/email", methods=["POST"])
    @login_required
    def change_account_email():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        current_password = data.get("current_password")
        new_email = data.get("new_email")

        if not isinstance(current_password, str) or not isinstance(new_email, str):
            return jsonify({
                "status": "error",
                "message": "Current password and a new email are required.",
            }), 400

        user = db.session.get(User, current_user_id())
        if user is None:
            session.clear()
            return authentication_required()

        if not check_password_hash(user.password_hash, current_password):
            return jsonify({
                "status": "error",
                "message": "Current password is incorrect.",
            }), 401

        normalized_email = normalize_email(new_email)
        if not normalized_email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
            return jsonify({
                "status": "error",
                "message": "Enter a valid email address.",
            }), 400

        if user.email == normalized_email:
            return jsonify({
                "status": "success",
                "message": "This is already your current email address.",
            }), 200

        existing_user = User.query.filter_by(email=normalized_email).first()
        if existing_user is not None and existing_user.id != user.id:
            return jsonify({
                "status": "error",
                "message": "An account with this email already exists.",
            }), 400

        user.email = normalized_email
        user.email_verified = False
        db.session.commit()

        token = issue_verification_token(user.id)
        try:
            send_verification_email(user.email, token)
        except Exception:
            app.logger.exception(
                "Account %s changed its email, but verification mail could not be sent.",
                user.id,
            )

        return jsonify({
            "status": "success",
            "message": "Email changed successfully. Please confirm the new address.",
        }), 200

    @app.route("/api/account/password", methods=["POST"])
    @login_required
    def change_account_password():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        current_password = data.get("current_password")
        new_password = data.get("new_password")

        if not isinstance(current_password, str) or not isinstance(new_password, str):
            return jsonify({
                "status": "error",
                "message": "Current password and a new password are required.",
            }), 400

        user = db.session.get(User, current_user_id())
        if user is None:
            session.clear()
            return authentication_required()

        if not check_password_hash(user.password_hash, current_password):
            return jsonify({
                "status": "error",
                "message": "Current password is incorrect.",
            }), 401

        if len(new_password) < 12 or len(new_password) > 1024:
            return jsonify({
                "status": "error",
                "message": "Password must contain at least 12 characters.",
            }), 400

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Password changed successfully.",
        }), 200

    @app.route("/api/account/clear-history", methods=["POST"])
    @login_required
    def clear_account_history():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        current_password = data.get("current_password")
        if not isinstance(current_password, str):
            return jsonify({
                "status": "error",
                "message": "Current password is required to clear your history.",
            }), 400

        user = db.session.get(User, current_user_id())
        if user is None:
            session.clear()
            return authentication_required()

        if not check_password_hash(user.password_hash, current_password):
            return jsonify({
                "status": "error",
                "message": "Current password is incorrect.",
            }), 401

        clear_user_history(user)

        return jsonify({
            "status": "success",
            "message": "Your document history has been cleared.",
        }), 200

    @app.route("/api/account", methods=["DELETE"])
    @login_required
    def delete_account():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "A JSON request body is required.",
            }), 400

        current_password = data.get("current_password")
        if not isinstance(current_password, str):
            return jsonify({
                "status": "error",
                "message": "Current password is required to delete your account.",
            }), 400

        user = db.session.get(User, current_user_id())
        if user is None:
            session.clear()
            return authentication_required()

        if not check_password_hash(user.password_hash, current_password):
            return jsonify({
                "status": "error",
                "message": "Current password is incorrect.",
            }), 401

        clear_user_history(user)
        db.session.delete(user)
        db.session.commit()
        session.clear()

        return jsonify({
            "status": "success",
            "message": "Your account and history have been deleted.",
        }), 200
