
import logging
import os

from logging.handlers import RotatingFileHandler

from flask import Flask

from app.database import db
from app.route_modules import register_routes


from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import argparse

from dotenv import load_dotenv

load_dotenv()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.environ.get(
        "RATELIMIT_STORAGE_URI",
        "memory://",
    ),
)



def configure_logging(app: Flask) -> None:
    """Configure application logging to console and rotating log file."""

    log_directory = os.path.join(app.instance_path, "logs")
    os.makedirs(log_directory, exist_ok=True)

    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = app.logger
    logger.setLevel(log_level)

    if not getattr(logger, "_retraction_logging_configured", False):
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        file_handler = RotatingFileHandler(
            os.path.join(log_directory, "retraction_checker.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        logger._retraction_logging_configured = True
    else:
        for handler in logger.handlers:
            handler.setLevel(log_level)


def create_app(test_config=None):
    """Create and configure the Flask application."""

    app = Flask(
        __name__,
        instance_path=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "instance")
        ),
    )

    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=(
            "sqlite:///"
            + os.path.join(
                app.instance_path,
                "retraction_checker.db",
            )
        ),
        SQLALCHEMY_BINDS={
            "users": (
                "sqlite:///"
                + os.path.join(
                    app.instance_path,
                    "users.db",
                )
            )
        },
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(
            os.environ.get(
                "SESSION_COOKIE_SECURE",
                "false",
            ).lower() == "true"
        ),
        LOG_LEVEL=os.environ.get("LOG_LEVEL", "INFO"),
        APP_ENV=os.environ.get("APP_ENV", "development").lower(),
    )

    if test_config is not None:
        app.config.update(test_config)

    # Use a test-only secret key during automated tests.
    if app.config.get("TESTING"):
        if not app.config.get("SECRET_KEY"):
            app.config["SECRET_KEY"] = "test-only-secret-key"
    else:
        # Require an explicitly configured secret key in production.
        secret_key = os.environ.get("SECRET_KEY")

        if not secret_key:
            raise RuntimeError(
                "SECRET_KEY environment variable must be configured."
            )

        app.config["SECRET_KEY"] = secret_key

    configure_logging(app)

    app.logger.info("Initializing Retraction Checker application.")

    db.init_app(app)

    limiter.init_app(app)

    register_routes(app)

    with app.app_context():
        # Import models before creating database tables.
        from app import models

        db.create_all()

    app.logger.info("Retraction Checker application initialized.")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run()
