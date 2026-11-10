import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MIGRATION_KEY = "verification_status_source_freshness_v2"


def migrate_database(database_path: str, backup_path: str | None = None) -> tuple[bool, int]:
    """Add verification_status and conservatively classify existing results."""

    database = Path(database_path)
    if not database.is_file():
        raise FileNotFoundError(f"Database file not found: {database}")

    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(detection_results)")
        }
        if not columns:
            raise RuntimeError("The detection_results table was not found.")
        migration_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone() is not None
        migration_applied = False
        if migration_table_exists:
            migration_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (MIGRATION_KEY,),
            ).fetchone() is not None
        if "verification_status" in columns and migration_applied:
            return False, 0

        if backup_path:
            backup = Path(backup_path)
            if backup.resolve() == database.resolve():
                raise ValueError("The backup path must differ from the database path.")
            if backup.exists():
                raise FileExistsError(f"Refusing to overwrite backup: {backup}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as backup_connection:
                connection.backup(backup_connection)

        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            if "verification_status" not in columns:
                connection.execute(
                    "ALTER TABLE detection_results "
                    "ADD COLUMN verification_status VARCHAR(30) "
                    "NOT NULL DEFAULT 'not_verified'"
                )
            result = connection.execute(
                """
                UPDATE detection_results
                SET verification_status = CASE
                    WHEN is_retracted = 1 THEN 'retracted'
                    WHEN EXISTS (
                        SELECT 1
                        FROM extracted_references AS ref
                        WHERE ref.id = detection_results.reference_id
                          AND (ref.doi IS NULL OR trim(ref.doi) = '')
                    ) THEN 'missing_doi'
                    ELSE 'not_verified'
                END
                """
            )
            affected_rows = result.rowcount
            connection.execute(
                "INSERT INTO schema_migrations (name) VALUES (?)",
                (MIGRATION_KEY,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        return True, affected_rows
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add the verification status column to the application database."
    )
    parser.add_argument("database", help="Path to the application SQLite database")
    parser.add_argument(
        "--backup-directory",
        default="backups",
        help="Directory for a pre-migration SQLite backup (default: backups)",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = Path(args.backup_directory) / (
        f"{Path(args.database).stem}_before_verification_status_{timestamp}.db"
    )
    migrated, affected_rows = migrate_database(args.database, str(backup_path))
    if migrated:
        print(f"Migration complete. Classified {affected_rows} existing results.")
        print(f"Backup saved to: {backup_path}")
    else:
        print("Migration skipped: verification_status already exists.")


if __name__ == "__main__":
    main()
