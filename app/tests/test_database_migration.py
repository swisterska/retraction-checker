import sqlite3

from app.migrations.verification_status import migrate_database
from app.migrations.email_verification import migrate_user_email_verification
from app.migrations.doi_identity import migrate_doi_identity, LEGACY_NOTE
from sqlalchemy import create_engine, text


def make_legacy_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE extracted_references (
                id INTEGER PRIMARY KEY,
                doi TEXT
            );
            CREATE TABLE detection_results (
                id INTEGER PRIMARY KEY,
                reference_id INTEGER NOT NULL,
                is_retracted BOOLEAN NOT NULL
            );
            INSERT INTO extracted_references VALUES (1, '10.1000/clear');
            INSERT INTO extracted_references VALUES (2, NULL);
            INSERT INTO extracted_references VALUES (3, '10.1000/retracted');
            INSERT INTO detection_results VALUES (1, 1, 0);
            INSERT INTO detection_results VALUES (2, 2, 0);
            INSERT INTO detection_results VALUES (3, 3, 1);
            """
        )


def test_verification_status_migration_backfills_and_creates_backup(tmp_path):
    database_path = tmp_path / "legacy.db"
    backup_path = tmp_path / "backup.db"
    make_legacy_database(database_path)

    migrated, affected = migrate_database(str(database_path), str(backup_path))

    assert migrated is True
    assert affected == 3
    assert backup_path.is_file()

    with sqlite3.connect(database_path) as connection:
        values = connection.execute(
            "SELECT id, verification_status FROM detection_results ORDER BY id"
        ).fetchall()
    assert values == [
        (1, "not_verified"),
        (2, "missing_doi"),
        (3, "retracted"),
    ]


def test_verification_status_migration_is_idempotent(tmp_path):
    database_path = tmp_path / "legacy.db"
    make_legacy_database(database_path)
    migrate_database(str(database_path))

    migrated, affected = migrate_database(str(database_path))

    assert migrated is False
    assert affected == 0


def test_migration_corrects_prior_unversioned_verified_statuses(tmp_path):
    database_path = tmp_path / "previously_migrated.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE extracted_references (id INTEGER PRIMARY KEY, doi TEXT);
            CREATE TABLE detection_results (
                id INTEGER PRIMARY KEY,
                reference_id INTEGER NOT NULL,
                is_retracted BOOLEAN NOT NULL,
                verification_status VARCHAR(30) NOT NULL
            );
            INSERT INTO extracted_references VALUES (1, '10.1000/clear');
            INSERT INTO extracted_references VALUES (2, NULL);
            INSERT INTO detection_results VALUES (1, 1, 0, 'verified');
            INSERT INTO detection_results VALUES (2, 2, 0, 'missing_doi');
            """
        )

    migrated, affected = migrate_database(str(database_path))

    assert migrated is True
    assert affected == 2
    with sqlite3.connect(database_path) as connection:
        values = connection.execute(
            "SELECT verification_status FROM detection_results ORDER BY id"
        ).fetchall()
    assert values == [("not_verified",), ("missing_doi",)]


def test_email_verification_migration_preserves_existing_accounts_as_verified(tmp_path):
    database_path = tmp_path / "legacy_users.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);"
            "INSERT INTO users VALUES (1, 'existing@example.org');"
        )

    engine = create_engine(f"sqlite:///{database_path}")
    assert migrate_user_email_verification(engine) is True
    assert migrate_user_email_verification(engine) is False
    assert len(list((tmp_path / "backups").glob("legacy_users_before_email_verification_*.db"))) == 1
    with engine.connect() as connection:
        verified = connection.execute(text(
            "SELECT email_verified FROM users WHERE id = 1"
        )).scalar_one()
    assert verified == 1


def test_doi_identity_migration_marks_old_verifications_for_review_and_backs_up(tmp_path):
    database_path = tmp_path / "legacy_results.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE detection_results (
                id INTEGER PRIMARY KEY,
                verification_status VARCHAR(30) NOT NULL,
                is_retracted BOOLEAN NOT NULL
            );
            INSERT INTO detection_results VALUES (1, 'verified', 0);
            INSERT INTO detection_results VALUES (2, 'retracted', 1);
            INSERT INTO detection_results VALUES (3, 'missing_doi', 0);
            """
        )

    engine = create_engine(f"sqlite:///{database_path}")
    migrated, backup_path = migrate_doi_identity(engine)

    assert migrated is True
    assert backup_path is not None
    assert (tmp_path / "backups").is_dir()
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT verification_status, verification_note, is_retracted "
            "FROM detection_results ORDER BY id"
        ).fetchall()
    assert rows == [
        ("not_verified", LEGACY_NOTE, 0),
        ("retracted", LEGACY_NOTE, 1),
        ("missing_doi", None, 0),
    ]

    assert migrate_doi_identity(engine) == (False, None)
