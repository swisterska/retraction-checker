
from functools import wraps

from flask import jsonify, session


def current_user_id():
    """Return the authenticated user's ID, or None."""
    user_id = session.get("user_id")
    return user_id if isinstance(user_id, int) else None


def authentication_required():
    """Return a standard JSON response for unauthenticated requests."""
    return jsonify({
        "status": "error",
        "message": "Authentication required.",
    }), 401


def login_required(view):
    """Require an authenticated session before executing a view."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            return authentication_required()
        return view(*args, **kwargs)

    return wrapped
