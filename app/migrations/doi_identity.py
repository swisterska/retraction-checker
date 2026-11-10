"""Store DOI identity check notes and conservatively relabel legacy results."""

from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text


LEGACY_NOTE = (
    "This result predates DOI-to-title matching. Review the DOI against the "
    "citation before relying on this status; upload the PDF again to re-check it."
)


def migrate_doi_identity(engine) -> tuple[bool, str | None]:
    """Add a note column and mark old DOI-only results for review.

    A timestamped backup is made before changing a persistent SQLite database.
    Existing positive retraction flags are preserved but annotated for review.
    """
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("detection_results")
    }
    if "verification_note" in columns:
        return False, None

    database_name = engine.url.database
    backup_path = None
    if database_name and database_name != ":memory:":
        database = Path(database_name).resolve()
        if database.is_file():
            backup_dir = database.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = backup_dir / f"{database.stem}_before_doi_identity_{timestamp}.db"
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
            for column in inspect(connection).get_columns("detection_results")
        }
        if "verification_note" in current_columns:
            return False, str(backup_path) if backup_path else None
        connection.execute(text(
            "ALTER TABLE detection_results ADD COLUMN verification_note TEXT"
        ))
        connection.execute(
            text("""
                UPDATE detection_results
                SET verification_note = :note,
                    verification_status = CASE
                        WHEN verification_status = 'verified' THEN 'not_verified'
                        ELSE verification_status
                    END
                WHERE verification_status IN ('verified', 'retracted')
            """),
            {"note": LEGACY_NOTE},
        )

    return True, str(backup_path) if backup_path else None
