import copy
import hashlib
import hmac
import secrets
import threading
import time
from uuid import uuid4


def current_guest_owner(session) -> str:
    """Return a stable, opaque owner key for this browser session."""

    guest_id = session.get("guest_session_id")
    if not isinstance(guest_id, str):
        guest_id = secrets.token_urlsafe(32)
        session["guest_session_id"] = guest_id
    return hashlib.sha256(guest_id.encode("utf-8")).hexdigest()


class GuestReportStore:
    """Bounded, process-local storage for short-lived guest reports."""

    def __init__(
        self,
        ttl_seconds=3600,
        max_reports=256,
        clock=time.monotonic,
        start_expirer=False,
    ):
        self.ttl_seconds = ttl_seconds
        self.max_reports = max_reports
        self.clock = clock
        self._reports = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        if start_expirer:
            threading.Thread(
                target=self._expiration_worker,
                name="guest-report-expirer",
                daemon=True,
            ).start()

    def _expiration_worker(self):
        while True:
            with self._condition:
                now = self.clock()
                self._purge_expired(now)
                if not self._reports:
                    self._condition.wait()
                    continue
                next_expiry = min(
                    record["expires_at_monotonic"]
                    for record in self._reports.values()
                )
                self._condition.wait(max(0, next_expiry - now))

    def _purge_expired(self, now):
        expired = [
            report_id
            for report_id, record in self._reports.items()
            if record["expires_at_monotonic"] <= now
        ]
        for report_id in expired:
            del self._reports[report_id]

    def create(self, owner_key: str, payload: dict):
        """Store a report, enforcing one active report per guest session."""

        with self._condition:
            now = self.clock()
            self._purge_expired(now)

            if any(
                hmac.compare_digest(record["owner_key"], owner_key)
                for record in self._reports.values()
            ):
                return None, "session_limit"
            if len(self._reports) >= self.max_reports:
                return None, "capacity"

            report_id = uuid4().hex
            report = copy.deepcopy(payload)
            report["report_id"] = report_id
            report["document"]["id"] = report_id
            self._reports[report_id] = {
                "owner_key": owner_key,
                "payload": report,
                "expires_at_monotonic": now + self.ttl_seconds,
            }
            self._condition.notify_all()
            return report_id, None

    def has_owner(self, owner_key: str) -> bool:
        with self._lock:
            self._purge_expired(self.clock())
            return any(
                hmac.compare_digest(record["owner_key"], owner_key)
                for record in self._reports.values()
            )

    def get(self, report_id: str, owner_key: str):
        with self._lock:
            self._purge_expired(self.clock())
            record = self._reports.get(report_id)
            if record is None or not hmac.compare_digest(
                record["owner_key"], owner_key
            ):
                return None
            return copy.deepcopy(record["payload"])

    def count(self) -> int:
        with self._lock:
            self._purge_expired(self.clock())
            return len(self._reports)
