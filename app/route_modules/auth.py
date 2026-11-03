
import hmac
import secrets

from flask import jsonify, request, session

from app.main import limiter

from app.database import db
from app.models import User
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

        return jsonify({
            "status": "success",
            "message": "Account created successfully.",
            "user": {
                "id": user.id,
                "email": user.email,
            },
        }), 201

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
