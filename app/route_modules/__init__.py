
from flask import Flask, jsonify


def register_routes(app: Flask) -> None:
    """Register all application routes."""

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            "status": "error",
            "code": "FILE_TOO_LARGE",
            "message": "The uploaded file exceeds the maximum allowed size of 16 MB.",
        }), 413

    @app.errorhandler(429)
    def too_many_requests(error):
        return jsonify({
            "status": "error",
            "code": "RATE_LIMITED",
            "message": "Too many requests. Please wait and try again.",
        }), 429

    from app.route_modules.auth import register_auth_routes
    from app.route_modules.documents import register_document_routes

    @app.route("/")
    def index():
        return "<h1>System Retraction Checker is working</h1>"

    register_auth_routes(app)
    register_document_routes(app)
