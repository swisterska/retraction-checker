"""Add email verification for new accounts without disabling existing users."""

from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text


def migrate_user_email_verification(engine) -> bool:
    """Add email_verified with existing accounts treated as already verified."""
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "email_verified" in columns:
        return False

    database_path = engine.url.database
    if database_path and database_path != ":memory:" and Path(database_path).is_file():
        database = Path(database_path).resolve()
        backup_directory = database.parent / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_directory / f"{database.stem}_before_email_verification_{timestamp}.db"
        source = sqlite3.connect(database)
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("users")
        }
        if "email_verified" in columns:
            return False
        connection.execute(text(
            "ALTER TABLE users ADD COLUMN email_verified "
            "BOOLEAN NOT NULL DEFAULT 1"
        ))
    return True
