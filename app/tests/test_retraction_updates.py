
import os
import time

import pandas as pd
import pytest
import requests

from app.services import retractions


VALID_CSV = (
    "OriginalPaperDOI,Reason\n"
    "10.1000/test123,Investigation\n"
    "10.1000/test456,Error in data\n"
)


def test_should_update_when_file_does_not_exist(tmp_path):
    path = tmp_path / "retractions.csv"

    assert retractions.should_update(str(path)) is True


def test_should_not_update_fresh_file(tmp_path):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    assert retractions.should_update(str(path)) is False


def test_should_update_old_file(tmp_path):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    old_time = time.time() - (25 * 3600)
    os.utime(path, (old_time, old_time))

    assert retractions.should_update(str(path)) is True


def test_validate_retractions_csv_accepts_valid_file(tmp_path):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    retractions.validate_retractions_csv(str(path))


def test_validate_retractions_csv_rejects_missing_doi_column(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("Title\nExample\n")

    with pytest.raises(ValueError, match="OriginalPaperDOI"):
        retractions.validate_retractions_csv(str(path))


def test_validate_retractions_csv_rejects_empty_dois(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("OriginalPaperDOI,Reason\n,\n")

    with pytest.raises(ValueError, match="no valid DOIs"):
        retractions.validate_retractions_csv(str(path))


def test_update_downloads_and_replaces_dataset(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"
    path.write_text("old dataset")

    class FakeResponse:
        content = VALID_CSV.encode("utf-8")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        retractions.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )

    retractions.update_retractions_from_gitlab(str(path))

    df = pd.read_csv(path)

    assert len(df) == 2
    assert "OriginalPaperDOI" in df.columns


def test_failed_download_preserves_old_dataset(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    def failed_request(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Network unavailable")

    monkeypatch.setattr(
        retractions.requests,
        "get",
        failed_request,
    )

    with pytest.raises(requests.exceptions.ConnectionError):
        retractions.update_retractions_from_gitlab(str(path))

    assert path.read_text() == VALID_CSV


def test_invalid_download_preserves_old_dataset(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    class FakeResponse:
        content = b"Title\nInvalid data\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        retractions.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(ValueError):
        retractions.update_retractions_from_gitlab(str(path))

    assert path.read_text() == VALID_CSV


def test_ensure_dataset_reuses_fresh_file(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Download should not happen")

    monkeypatch.setattr(
        retractions,
        "update_retractions_from_gitlab",
        unexpected_download,
    )

    assert retractions.ensure_retractions_dataset(str(path)) is False


def test_ensure_dataset_falls_back_to_old_file(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"
    path.write_text(VALID_CSV)

    old_time = time.time() - (25 * 3600)
    os.utime(path, (old_time, old_time))

    def failed_download(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Network unavailable")

    monkeypatch.setattr(
        retractions,
        "update_retractions_from_gitlab",
        failed_download,
    )

    assert retractions.ensure_retractions_dataset(str(path)) is False
    assert path.read_text() == VALID_CSV


def test_ensure_dataset_raises_if_no_local_file(tmp_path, monkeypatch):
    path = tmp_path / "retractions.csv"

    def failed_download(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Network unavailable")

    monkeypatch.setattr(
        retractions,
        "update_retractions_from_gitlab",
        failed_download,
    )

    with pytest.raises(requests.exceptions.ConnectionError):
        retractions.ensure_retractions_dataset(str(path))
