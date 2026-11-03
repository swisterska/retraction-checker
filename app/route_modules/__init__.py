
from flask import Flask, jsonify


def register_routes(app: Flask) -> None:
    """Register all application routes."""

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            "status": "error",
            "message": "File is too large. Maximum request size is 16 MB.",
        }), 413

    from app.route_modules.auth import register_auth_routes
    from app.route_modules.documents import register_document_routes

    @app.route("/")
    def index():
        return "<h1>System Retraction Checker is working</h1>"

    register_auth_routes(app)
    register_document_routes(app)
