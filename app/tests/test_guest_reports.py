from app.services.guest_reports import GuestReportStore, current_guest_owner


def test_guest_report_store_limits_session_and_protects_report_owner():
    store = GuestReportStore(ttl_seconds=60, max_reports=3)
    payload = {"document": {"id": None}, "results": []}

    report_id, reason = store.create("owner-a", payload)

    assert reason is None
    assert store.has_owner("owner-a")
    assert store.create("owner-a", payload) == (None, "session_limit")
    assert store.get(report_id, "owner-b") is None
    report = store.get(report_id, "owner-a")
    assert report["report_id"] == report_id
    assert report["document"]["id"] == report_id


def test_guest_report_store_expires_records():
    current_time = [10.0]
    store = GuestReportStore(
        ttl_seconds=5,
        max_reports=2,
        clock=lambda: current_time[0],
    )
    report_id, _ = store.create(
        "owner-a",
        {"document": {"id": None}, "results": []},
    )

    current_time[0] = 15.0

    assert store.get(report_id, "owner-a") is None
    assert store.count() == 0


def test_guest_owner_key_is_stable_but_does_not_expose_session_id():
    session = {}

    owner_key = current_guest_owner(session)

    assert session["guest_session_id"]
    assert owner_key == current_guest_owner(session)
    assert owner_key != session["guest_session_id"]
