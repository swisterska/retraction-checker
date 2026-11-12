"""Add a persistent last-check timestamp to saved documents."""

from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text


def migrate_document_last_check(engine) -> tuple[bool, str | None]:
    """Add and backfill ``uploaded_documents.last_checked_at`` once."""
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("uploaded_documents")
    }
    if "last_checked_at" in columns:
        return False, None

    database_name = engine.url.database
    backup_path = None
    if database_name and database_name != ":memory:":
        database = Path(database_name).resolve()
        if database.is_file():
            backup_dir = database.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / (
                f"{database.stem}_before_document_last_check_{timestamp}.db"
            )
            source = sqlite3.connect(database)
            target = sqlite3.connect(backup_path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()

    with engine.begin() as connection:
        current_columns = {
            column["name"]
            for column in inspect(connection).get_columns("uploaded_documents")
        }
        if "last_checked_at" in current_columns:
            return False, str(backup_path) if backup_path else None
        connection.execute(
            text("ALTER TABLE uploaded_documents ADD COLUMN last_checked_at DATETIME")
        )
        connection.execute(text(
            "UPDATE uploaded_documents "
            "SET last_checked_at = upload_date "
            "WHERE last_checked_at IS NULL"
        ))

    return True, str(backup_path) if backup_path else None
