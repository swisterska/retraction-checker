"""Set up and start the Retraction Checker backend.

This module creates the Flask application, loads its settings, connects the
database and request limiter, registers API routes, and prepares database
tables and migrations. When this file is run directly, it starts the Flask
web server and a separate worker process for queued PDF analyses. The worker
and the PDF analysis pipeline are implemented in other modules.
"""

# Python standard library imports
import logging
import os
import subprocess
import sys

# Flask and related imports
from logging.handlers import RotatingFileHandler
from flask import Flask

# Database and route registration imports
from app.database import db
from app.route_modules import register_routes

# Rate limiting imports
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables from .env file if present
from dotenv import load_dotenv

load_dotenv()

# Limiter recognizes the client IP address for rate limiting purposes.
# There are no default limits; they are set in the route modules.
# Limiter storage are in memory by default, but can be configured with the RATELIMIT_STORAGE_URI environment variable.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.environ.get(
        "RATELIMIT_STORAGE_URI",
        "memory://",
    ),
)



def configure_logging(app: Flask) -> None:
    """Set up where the application writes its log messages.

    Messages go to the console and to a log file inside Flask's instance
    folder. The file is rotated when it reaches 5 MB, keeping up to three
    older files so the log folder does not grow without limit.

    Args:
        app: The Flask application whose logger should be configured.
    """

    # Choose the log directory inside the Flask instance folder, creating it if needed.
    log_directory = os.path.join(app.instance_path, "logs")
    os.makedirs(log_directory, exist_ok=True)

    # Set the log level based on the LOG_LEVEL environment variable, defaulting to INFO.
    log_level_name = app.config.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logger = app.logger
    logger.setLevel(log_level)

    #Checks if the logger has already been configured to avoid adding duplicate handlers.
    if not getattr(logger, "_retraction_logging_configured", False):
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # If the logger has not been configured yet, add a console handler and a rotating file handler.
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        # File can reach up to 5 MB and after that new one is created, 
        # keeping up to three older files so the log folder does not grow without limit.
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


def start_analysis_worker():
    """Launch the background worker for queued PDF analyses."""

    if os.environ.get("AUTO_START_ANALYSIS_WORKER", "true").lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None

    # The worker is started as a separate process using the same Python interpreter
    # We get immediate feedback if the worker fails to start, and it can be terminated when the server stops.
    command = [sys.executable, "-m", "app.analysis_worker"]
    return subprocess.Popen(
        command,
        start_new_session=True,
    )


def run_server(app, port):
    """Run Flask and keep its worker lifecycle tied to the server process.
    
    It starts the worker, runs Flask, and when Flask stops, worker stops as well"""
    
    worker = start_analysis_worker()
    try:
        app.run(host="127.0.0.1", port=port)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=10)


def create_app(test_config=None):
    """Create and prepare the Flask application.

    This function builds the application and connects the parts it needs
    before it can handle requests. It sets the application settings, prepares
    the folder for local data, connects the databases and request limiter,
    registers the API routes, and prepares the database tables.
    
    Args:
        test_config: Optional settings to apply when creating the application,
            usually used by tests.

    Returns:
        A configured Flask application.

    Raises:
        RuntimeError: If ``SECRET_KEY`` is missing outside testing mode."""

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
        #Set the maximum upload size to 16 MB
        MAX_UPLOAD_SIZE_BYTES=16 * 1024 * 1024,
        ANALYSIS_UPLOAD_DIR=os.environ.get("ANALYSIS_UPLOAD_DIR"),
        MAX_CONTENT_LENGTH=(16 * 1024 * 1024) + (64 * 1024),
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

    if app.config.get("TESTING"):
        if not app.config.get("SECRET_KEY"):
            app.config["SECRET_KEY"] = "test-only-secret-key"

    # If not testing, ensure that a secret key is set in the environment.        
    else:
        secret_key = os.environ.get("SECRET_KEY")

        if not secret_key:
            raise RuntimeError(
                "SECRET_KEY environment variable must be configured."
            )

        app.config["SECRET_KEY"] = secret_key


    # Set up logging for the application
    configure_logging(app)
    app.logger.info("Initializing Retraction Checker application.")

    # Connect the database
    db.init_app(app)

    # Connect the request limiter to count requests 
    limiter.init_app(app)

    # Register the API routes with the application. Tells Flask what to do when a request comes in for a specific URL.
    register_routes(app)


    with app.app_context():
        from app import models

        # Create the database tables if they don't exist yet.
        db.create_all()

        # Update the database schema to the latest version if needed.
        from app.migrations.email_verification import migrate_user_email_verification
        migrate_user_email_verification(db.engines["users"])

        # Updatte the database with the DOI identity migration if needed. This adds a new column to the detection_results table and marks old DOI-only results for review.
        from app.migrations.doi_identity import migrate_doi_identity
        migrated, backup_path = migrate_doi_identity(db.engine)
        #If the migration was perfmormed we receive the message and log it.
        if migrated:
            app.logger.info(
                "DOI identity migration completed%s.",
                f"; backup saved to {backup_path}" if backup_path else "",
            )

        # Update the database with the document last-check migration if needed. 
        from app.migrations.document_last_check import migrate_document_last_check
        migrated, backup_path = migrate_document_last_check(db.engine)
        if migrated:
            app.logger.info(
                "Document last-check migration completed%s.",
                f"; backup saved to {backup_path}" if backup_path else "",
            )

    app.logger.info("Retraction Checker application initialized.")

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", os.environ.get("FLASK_RUN_PORT", "5001")))
    run_server(app, port)
