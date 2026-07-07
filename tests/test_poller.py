from __future__ import annotations

import copy
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from skytracer import poller, settings_store, watchdog
from skytracer.config import validate
from skytracer.db import init_db
from skytracer.poller import LAST_POLL_AT_KEY, _resolve_queries, is_poll_due, run_poll_once
from skytracer.settings_store import seed_if_empty
from skytracer.sources import google as google_module


def _fake_flight(price: float, airports: list[str], airlines: list[str]):
    segments = [
        SimpleNamespace(
            from_airport=SimpleNamespace(code=airports[i]),
            to_airport=SimpleNamespace(code=airports[i + 1]),
            duration=100,
        )
        for i in range(len(airports) - 1)
    ]
    return SimpleNamespace(price=price, airlines=airlines, flights=segments)


def _seeded_conn(tmp_path, valid_raw_config: dict):
    conn = init_db(tmp_path / "skytracer.db")
    result = validate(valid_raw_config)
    seed_if_empty(conn, result.config)
    return conn


def test_run_poll_once_stores_cheapest_fare(tmp_path, monkeypatch, valid_raw_config: dict) -> None:
    conn = _seeded_conn(tmp_path, valid_raw_config)
    fakes = [
        _fake_flight(1579.0, ["OKC", "DEN", "NRT"], ["United"]),
        _fake_flight(1200.0, ["OKC", "NRT"], ["ANA"]),
    ]
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: fakes)

    run_poll_once(conn)

    row = conn.execute("SELECT * FROM observations").fetchone()
    assert row is not None
    assert row["price"] == 1200.0
    assert row["source"] == "google"
    assert row["origin"] == "OKC"
    assert row["destination"] == "NRT"
    assert row["route_key"]


def test_run_poll_once_stores_top_n_fares_ranked_by_price(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["dashboard"]["top_n_fares"] = 2
    valid_raw_config["trips"][0]["trip"]["fixed"] = {
        "enabled": True, "depart_date": "2026-09-01", "return_date": "2026-09-11"
    }
    valid_raw_config["trips"][0]["trip"]["flexible"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    fakes = [
        _fake_flight(1579.0, ["OKC", "DEN", "NRT"], ["United"]),
        _fake_flight(1200.0, ["OKC", "NRT"], ["ANA"]),
        _fake_flight(999.0, ["OKC", "LAX", "NRT"], ["Delta"]),
    ]
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: fakes)

    run_poll_once(conn)

    rows = conn.execute("SELECT price, rank FROM observations ORDER BY rank ASC").fetchall()
    # top_n_fares=2 caps storage to the 2 cheapest, not all 3 found
    assert [(r["price"], r["rank"]) for r in rows] == [(999.0, 0), (1200.0, 1)]


def test_run_poll_once_no_sources_enabled_does_not_crash(tmp_path, valid_raw_config: dict) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)

    run_poll_once(conn)  # should log an error, not raise

    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_run_poll_once_empty_fares_does_not_crash(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: [])
    monkeypatch.setattr(google_module.time, "sleep", lambda _s: None)

    run_poll_once(conn)  # should log an error, not raise

    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_run_poll_once_source_exception_does_not_crash(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    conn = _seeded_conn(tmp_path, valid_raw_config)

    def always_fails(q):
        raise RuntimeError("boom")

    monkeypatch.setattr(google_module.ff, "get_flights", always_fails)
    monkeypatch.setattr(google_module.time, "sleep", lambda _s: None)

    run_poll_once(conn)  # should log and swallow, not raise

    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_run_poll_once_uses_fixed_dates_when_enabled(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["trip"]["flexible"]["enabled"] = False
    valid_raw_config["trips"][0]["trip"]["fixed"] = {
        "enabled": True,
        "depart_date": "2026-10-01",
        "return_date": "2026-10-11",
    }
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )

    run_poll_once(conn)

    row = conn.execute("SELECT * FROM observations").fetchone()
    assert row["depart_date"] == "2026-10-01"
    assert row["return_date"] == "2026-10-11"


# --- flexible-window scanning (Phase 7) --------------------------------------


def test_resolve_queries_fixed_trip_returns_one_query(valid_raw_config: dict) -> None:
    valid_raw_config["trips"][0]["trip"]["flexible"]["enabled"] = False
    valid_raw_config["trips"][0]["trip"]["fixed"] = {
        "enabled": True,
        "depart_date": "2026-10-01",
        "return_date": "2026-10-11",
    }
    config = validate(valid_raw_config).config
    queries = _resolve_queries(config.trips[0].trip)
    assert len(queries) == 1
    assert queries[0].depart_date == "2026-10-01"
    assert queries[0].return_date == "2026-10-11"


def test_resolve_queries_flexible_trip_samples_every_step(valid_raw_config: dict) -> None:
    valid_raw_config["trips"][0]["trip"]["flexible"] = {
        "enabled": True,
        "earliest_depart": "2026-09-01",
        "latest_depart": "2026-09-10",
        "trip_length_days": 10,
        "scan_step_days": 3,
    }
    config = validate(valid_raw_config).config
    queries = _resolve_queries(config.trips[0].trip)

    assert [q.depart_date for q in queries] == [
        "2026-09-01",
        "2026-09-04",
        "2026-09-07",
        "2026-09-10",
    ]
    assert queries[0].return_date == "2026-09-11"  # depart + trip_length_days
    assert queries[-1].return_date == "2026-09-20"


def test_run_poll_once_picks_cheapest_across_sampled_dates(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["trip"]["flexible"] = {
        "enabled": True,
        "earliest_depart": "2026-09-01",
        "latest_depart": "2026-09-10",
        "trip_length_days": 10,
        "scan_step_days": 5,
    }
    conn = _seeded_conn(tmp_path, valid_raw_config)

    def by_depart_date(q):
        # a different price per sampled date, so the poll must scan more
        # than just the first date to find the true cheapest.
        depart_date = q._flights[0].date
        price = {"2026-09-01": 1500.0, "2026-09-06": 800.0}.get(depart_date, 2000.0)
        return [_fake_flight(price, ["OKC", "NRT"], ["ANA"])]

    monkeypatch.setattr(google_module.ff, "get_flights", by_depart_date)

    run_poll_once(conn)

    row = conn.execute("SELECT * FROM observations").fetchone()
    assert row["price"] == 800.0
    assert row["depart_date"] == "2026-09-06"


# --- scheduling (Phase 9) -----------------------------------------------------


def test_is_poll_due_true_when_never_polled(tmp_path, valid_raw_config: dict) -> None:
    conn = _seeded_conn(tmp_path, valid_raw_config)
    config = validate(valid_raw_config).config
    assert is_poll_due(conn, config) is True


def test_is_poll_due_false_before_interval_elapses(tmp_path, valid_raw_config: dict) -> None:
    valid_raw_config["schedule"]["every_hours"] = 6
    conn = _seeded_conn(tmp_path, valid_raw_config)
    config = validate(valid_raw_config).config
    now = datetime(2026, 1, 1, tzinfo=UTC)
    settings_store.set(conn, LAST_POLL_AT_KEY, now.isoformat())

    assert is_poll_due(conn, config, now=now + timedelta(hours=3)) is False
    assert is_poll_due(conn, config, now=now + timedelta(hours=6)) is True
    assert is_poll_due(conn, config, now=now + timedelta(hours=7)) is True


def test_run_poll_once_stamps_last_poll_at_even_on_failure(
    tmp_path, valid_raw_config: dict
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    assert settings_store.get(conn, LAST_POLL_AT_KEY) is None

    run_poll_once(conn)  # no sources enabled -> fails, but still an attempt

    assert settings_store.get(conn, LAST_POLL_AT_KEY) is not None


# --- watchdog integration ----------------------------------------------------


def test_run_poll_once_resets_watchdog_on_success(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    conn = _seeded_conn(tmp_path, valid_raw_config)
    watchdog.record_failure(conn)
    watchdog.record_failure(conn)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )

    run_poll_once(conn)

    from skytracer import settings_store

    assert settings_store.get(conn, watchdog.CONSECUTIVE_FAILURES_KEY) == 0


def test_run_poll_once_watchdog_fires_after_threshold_failures(
    tmp_path, valid_raw_config: dict, caplog
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)

    with caplog.at_level(logging.ERROR, logger="skytracer.poller"):
        for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD):
            run_poll_once(conn)

    assert "consecutive times" in caplog.text


def test_run_poll_once_watchdog_silent_before_threshold(
    tmp_path, valid_raw_config: dict, caplog
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)

    with caplog.at_level(logging.ERROR, logger="skytracer.poller"):
        for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD - 1):
            run_poll_once(conn)

    assert "consecutive times" not in caplog.text


def test_run_poll_once_watchdog_sends_notification_at_threshold(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    fake_notifier = _FakeNotifier()
    monkeypatch.setattr(poller, "build_notifier", lambda config: fake_notifier)

    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD):
        run_poll_once(conn)

    assert len(fake_notifier.sent) == 1
    assert "tracker is broken" in fake_notifier.sent[0]


def test_run_poll_once_watchdog_does_not_notify_before_threshold(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    fake_notifier = _FakeNotifier()
    monkeypatch.setattr(poller, "build_notifier", lambda config: fake_notifier)

    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD - 1):
        run_poll_once(conn)

    assert fake_notifier.sent == []


def test_run_poll_once_watchdog_does_not_spam_after_threshold(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    """Fires once at the crossing point, not again on every subsequent
    failure during a prolonged outage."""
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    fake_notifier = _FakeNotifier()
    monkeypatch.setattr(poller, "build_notifier", lambda config: fake_notifier)

    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD + 3):
        run_poll_once(conn)

    assert len(fake_notifier.sent) == 1


def test_run_poll_once_watchdog_notification_failure_does_not_crash(
    tmp_path, valid_raw_config: dict
) -> None:
    valid_raw_config["sources"]["google"]["enabled"] = False
    conn = _seeded_conn(tmp_path, valid_raw_config)
    # default seed config's whatsapp/callmebot has no credentials, so the
    # real notifier's send_text() will raise — must not propagate.
    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD):
        run_poll_once(conn)  # should not raise


# --- alert integration --------------------------------------------------------


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, alert):
        self.sent.append(alert)

    def send_text(self, text):
        self.sent.append(text)


def test_run_poll_once_fires_alert_on_threshold_cross(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["alerts"]["threshold_price"] = 600.0
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )
    monkeypatch.setattr(poller, "build_notifier", lambda config: _FakeNotifier())

    run_poll_once(conn)

    rows = conn.execute("SELECT reason FROM alert_log").fetchall()
    assert [r["reason"] for r in rows] == ["threshold"]


def test_run_poll_once_alert_respects_cooldown_across_polls(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["alerts"]["threshold_price"] = 600.0
    valid_raw_config["trips"][0]["alerts"]["cooldown_hours"] = 12
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )
    monkeypatch.setattr(poller, "build_notifier", lambda config: _FakeNotifier())

    run_poll_once(conn)
    run_poll_once(conn)  # immediately after — cooldown should suppress a second alert

    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 1


def test_run_poll_once_alert_not_suppressed_after_failed_send_retries_next_poll(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    """The default seed config ships whatsapp/callmebot with no credentials,
    so a real send fails. That failure must NOT burn the cooldown — the
    very next poll should try (and, with a working notifier, succeed) again.
    """
    valid_raw_config["trips"][0]["alerts"]["threshold_price"] = 600.0
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )

    run_poll_once(conn)  # unconfigured whatsapp -> send fails
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0

    fake_notifier = _FakeNotifier()
    monkeypatch.setattr(poller, "build_notifier", lambda config: fake_notifier)
    run_poll_once(conn)  # now it succeeds — not blocked by a phantom cooldown
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 1


def test_run_poll_once_sends_notification_when_alert_fires(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["alerts"]["threshold_price"] = 600.0
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )

    sent = {}

    class FakeNotifier:
        def send(self, alert):
            sent["alert"] = alert

    monkeypatch.setattr(poller, "build_notifier", lambda config: FakeNotifier())

    run_poll_once(conn)

    assert sent["alert"].price == 500.0
    assert sent["alert"].reasons == ["threshold"]
    assert sent["alert"].all_time_low == 500.0
    assert sent["alert"].dashboard_url is not None


def test_run_poll_once_zero_trips_does_not_crash(tmp_path, valid_raw_config: dict) -> None:
    valid_raw_config["trips"] = []
    conn = _seeded_conn(tmp_path, valid_raw_config)

    run_poll_once(conn)  # nothing configured -> log and return, not raise

    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    assert settings_store.get(conn, watchdog.CONSECUTIVE_FAILURES_KEY, 0) == 0


def test_run_poll_once_one_trip_failing_does_not_trip_watchdog(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    """Two trips, one comes up empty every poll — the watchdog must stay
    reset (this is a partial failure, not the whole tracker being broken),
    and no "tracker is broken" notification should fire.
    """
    second_trip = copy.deepcopy(valid_raw_config["trips"][0])
    second_trip["trip"]["origin"] = "DFW"
    second_trip["trip"]["destination"] = "LHR"
    valid_raw_config["trips"].append(second_trip)
    conn = _seeded_conn(tmp_path, valid_raw_config)

    def only_okc_has_fares(q):
        if q._flights[0].from_airport == "OKC":
            return [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
        return []

    monkeypatch.setattr(google_module.ff, "get_flights", only_okc_has_fares)
    monkeypatch.setattr(google_module.time, "sleep", lambda _s: None)
    fake_notifier = _FakeNotifier()
    monkeypatch.setattr(poller, "build_notifier", lambda config: fake_notifier)

    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD + 2):
        run_poll_once(conn)

    assert settings_store.get(conn, watchdog.CONSECUTIVE_FAILURES_KEY) == 0
    assert not any("tracker is broken" in s for s in fake_notifier.sent if isinstance(s, str))

    routes = {
        row["route_key"]
        for row in conn.execute("SELECT DISTINCT route_key FROM observations")
    }
    assert len(routes) == 1  # only the OKC->NRT trip ever stored anything


def test_run_poll_once_all_trips_failing_still_trips_watchdog(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    second_trip = copy.deepcopy(valid_raw_config["trips"][0])
    second_trip["trip"]["origin"] = "DFW"
    second_trip["trip"]["destination"] = "LHR"
    valid_raw_config["trips"].append(second_trip)
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: [])
    monkeypatch.setattr(google_module.time, "sleep", lambda _s: None)

    for _ in range(watchdog.CONSECUTIVE_FAILURE_THRESHOLD):
        run_poll_once(conn)

    failures = settings_store.get(conn, watchdog.CONSECUTIVE_FAILURES_KEY)
    assert failures == watchdog.CONSECUTIVE_FAILURE_THRESHOLD


def test_run_poll_once_notification_failure_does_not_crash(
    tmp_path, monkeypatch, valid_raw_config: dict
) -> None:
    valid_raw_config["trips"][0]["alerts"]["threshold_price"] = 600.0
    conn = _seeded_conn(tmp_path, valid_raw_config)
    monkeypatch.setattr(
        google_module.ff, "get_flights", lambda q: [_fake_flight(500.0, ["OKC", "NRT"], ["ANA"])]
    )

    class FailingNotifier:
        def send(self, alert):
            raise RuntimeError("network is down")

    monkeypatch.setattr(poller, "build_notifier", lambda config: FailingNotifier())

    run_poll_once(conn)  # should log and swallow, not raise

    # One poll happened (rank=0 identifies "the winner of one poll" — a poll
    # can store several rows now, per-poll, via Phase 10's top-N fares).
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE rank = 0").fetchone()[0] == 1
    # a failed send must not be logged to alert_log — that would burn the
    # cooldown window and silently eat the alert for cooldown_hours
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0
