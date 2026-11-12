import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text

from app.migrations.document_last_check import migrate_document_last_check


def test_document_last_check_migration_backfills_from_upload_date_and_backs_up(tmp_path):
    database_path = tmp_path / "legacy_documents.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE uploaded_documents (
                id INTEGER PRIMARY KEY,
                upload_date DATETIME NOT NULL
            );
            INSERT INTO uploaded_documents VALUES (1, '2026-11-01 09:30:00');
            """
        )

    engine = create_engine(f"sqlite:///{database_path}")
    migrated, backup_path = migrate_document_last_check(engine)

    assert migrated is True
    assert backup_path is not None
    assert Path(backup_path).is_file()
    with engine.connect() as connection:
        values = connection.execute(text(
            "SELECT upload_date, last_checked_at FROM uploaded_documents WHERE id = 1"
        )).one()
    assert values[0] == values[1] == "2026-11-01 09:30:00"
    assert migrate_document_last_check(engine) == (False, None)
