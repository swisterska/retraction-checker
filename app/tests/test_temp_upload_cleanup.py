import os
import time

from app.route_modules.documents import cleanup_stale_uploads


def test_cleanup_removes_only_expired_app_named_pdfs(tmp_path):
    expired = tmp_path / ("a" * 32 + ".pdf")
    recent = tmp_path / ("b" * 32 + ".pdf")
    user_file = tmp_path / "notes.pdf"
    wrong_extension = tmp_path / ("c" * 32 + ".txt")
    for path in (expired, recent, user_file, wrong_extension):
        path.write_bytes(b"temporary")

    old_time = time.time() - 7200
    os.utime(expired, (old_time, old_time))
    os.utime(user_file, (old_time, old_time))
    os.utime(wrong_extension, (old_time, old_time))

    removed = cleanup_stale_uploads(tmp_path, max_age_seconds=3600)

    assert removed == 1
    assert not expired.exists()
    assert recent.exists()
    assert user_file.exists()
    assert wrong_extension.exists()
