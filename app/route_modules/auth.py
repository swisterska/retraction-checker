
import hmac
import secrets

from flask import jsonify, request, session

from app.main import limiter

from app.database import db
from app.models import User
from app.services.email_service import send_verification_email
from app.services.email_verification import confirm_email, issue_verification_token
from app.services.user_service import (
    register_user,
    authenticate_user,
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
