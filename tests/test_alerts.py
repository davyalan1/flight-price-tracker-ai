from __future__ import annotations

from datetime import UTC, datetime, timedelta

from skytracer.alerts import (
    REASON_DROP,
    REASON_NEW_LOW,
    REASON_THRESHOLD,
    decide_alert,
    evaluate_alert_reasons,
    get_last_alert_sent_at,
    log_alert,
    record_alert_sent,
    should_send_alert,
)
from skytracer.config import AlertsConfig
from skytracer.db import init_db
from skytracer.models import PricePoint


def _points(*prices: float) -> list[PricePoint]:
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        PricePoint(observed_at=(base + timedelta(days=i)).isoformat(), price=p)
        for i, p in enumerate(prices)
    ]


# --- evaluate_alert_reasons (pure) ------------------------------------------


def test_no_reasons_when_nothing_triggers() -> None:
    points = _points(900.0, 950.0)  # price went up: no drop, no new low, above threshold
    reasons = evaluate_alert_reasons(
        points, threshold_price=500.0, drop_percent=50.0, notify_on_new_low=True
    )
    assert reasons == []


def test_threshold_reason_fires_at_or_below_threshold() -> None:
    points = _points(1000.0, 900.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=900.0, drop_percent=100.0, notify_on_new_low=False
    )
    assert reasons == [REASON_THRESHOLD]


def test_threshold_reason_does_not_fire_above_threshold() -> None:
    points = _points(1000.0, 901.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=900.0, drop_percent=100.0, notify_on_new_low=False
    )
    assert REASON_THRESHOLD not in reasons


def test_new_low_reason_fires_when_current_beats_all_prior() -> None:
    points = _points(1000.0, 950.0, 900.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=100.0, notify_on_new_low=True
    )
    assert reasons == [REASON_NEW_LOW]


def test_new_low_reason_does_not_fire_when_disabled() -> None:
    points = _points(1000.0, 950.0, 900.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=100.0, notify_on_new_low=False
    )
    assert REASON_NEW_LOW not in reasons


def test_new_low_reason_does_not_fire_on_first_ever_observation() -> None:
    points = _points(900.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=100.0, notify_on_new_low=True
    )
    assert REASON_NEW_LOW not in reasons


def test_new_low_reason_does_not_fire_when_tying_not_beating() -> None:
    points = _points(1000.0, 900.0, 900.0)
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=100.0, notify_on_new_low=True
    )
    assert REASON_NEW_LOW not in reasons


def test_drop_reason_fires_when_drop_meets_threshold() -> None:
    points = _points(1000.0, 900.0)  # 10% drop
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=10.0, notify_on_new_low=False
    )
    assert reasons == [REASON_DROP]


def test_drop_reason_does_not_fire_below_threshold_percent() -> None:
    points = _points(1000.0, 950.0)  # 5% drop
    reasons = evaluate_alert_reasons(
        points, threshold_price=1.0, drop_percent=10.0, notify_on_new_low=False
    )
    assert REASON_DROP not in reasons


def test_multiple_reasons_can_fire_together() -> None:
    points = _points(1000.0, 500.0)  # 50% drop, new low, and under threshold
    reasons = evaluate_alert_reasons(
        points, threshold_price=600.0, drop_percent=10.0, notify_on_new_low=True
    )
    assert set(reasons) == {REASON_THRESHOLD, REASON_NEW_LOW, REASON_DROP}


def test_empty_points_yields_no_reasons() -> None:
    reasons = evaluate_alert_reasons(
        [], threshold_price=1.0, drop_percent=1.0, notify_on_new_low=True
    )
    assert reasons == []


# --- should_send_alert (pure cooldown gate) ---------------------------------


def test_should_send_alert_false_when_no_reasons() -> None:
    assert should_send_alert([], last_alert_sent_at=None, cooldown_hours=12) is False


def test_should_send_alert_true_when_never_alerted_before() -> None:
    assert should_send_alert(["threshold"], last_alert_sent_at=None, cooldown_hours=12) is True


def test_should_send_alert_false_within_cooldown() -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    last_sent = (now - timedelta(hours=1)).isoformat()
    assert (
        should_send_alert(
            ["threshold"], last_alert_sent_at=last_sent, cooldown_hours=12, now=now
        )
        is False
    )


def test_should_send_alert_true_after_cooldown_elapses() -> None:
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    last_sent = (now - timedelta(hours=13)).isoformat()
    assert (
        should_send_alert(
            ["threshold"], last_alert_sent_at=last_sent, cooldown_hours=12, now=now
        )
        is True
    )


# --- alert_log plumbing + decide_alert/record_alert_sent (DB-touching) -----


def _config(**overrides) -> AlertsConfig:
    base = dict(threshold_price=900.0, drop_percent=10.0, notify_on_new_low=True, cooldown_hours=12)
    base.update(overrides)
    return AlertsConfig(**base)


def test_log_alert_and_get_last_alert_sent_at(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    assert get_last_alert_sent_at(conn, "route-a") is None

    log_alert(
        conn, route_key="route-a", reason="threshold", price=800.0,
        sent_at="2026-06-01T00:00:00+00:00",
    )
    assert get_last_alert_sent_at(conn, "route-a") == "2026-06-01T00:00:00+00:00"

    log_alert(
        conn, route_key="route-a", reason="new_low", price=800.0,
        sent_at="2026-06-02T00:00:00+00:00",
    )
    assert get_last_alert_sent_at(conn, "route-a") == "2026-06-02T00:00:00+00:00"


def test_decide_alert_does_not_write_to_alert_log(tmp_path) -> None:
    """decide_alert is read-only — the caller records the send explicitly,
    only after actually delivering the notification (see poller.py)."""
    conn = init_db(tmp_path / "skytracer.db")
    points = _points(1000.0, 500.0)  # threshold + new_low + drop, all at once
    fired = decide_alert(
        conn, route_key="route-a", points=points, config=_config(threshold_price=600.0)
    )
    assert set(fired) == {REASON_THRESHOLD, REASON_NEW_LOW, REASON_DROP}
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0


def test_record_alert_sent_writes_one_row_per_reason(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    record_alert_sent(
        conn,
        route_key="route-a",
        reasons=[REASON_THRESHOLD, REASON_NEW_LOW],
        price=500.0,
        sent_at="2026-06-01T00:00:00+00:00",
    )
    rows = conn.execute(
        "SELECT reason FROM alert_log WHERE route_key = ? ORDER BY reason", ("route-a",)
    ).fetchall()
    assert sorted(r["reason"] for r in rows) == sorted([REASON_THRESHOLD, REASON_NEW_LOW])


def test_decide_alert_respects_cooldown_on_repeat_trigger(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)

    points = _points(1000.0, 500.0)
    fired_first = decide_alert(
        conn, route_key="route-a", points=points, config=_config(threshold_price=600.0), now=now
    )
    assert fired_first
    record_alert_sent(
        conn, route_key="route-a", reasons=fired_first, price=500.0, sent_at=now.isoformat()
    )

    # same trigger fires again 1 hour later — cooldown (12h) should block it
    later = now + timedelta(hours=1)
    fired_second = decide_alert(
        conn,
        route_key="route-a",
        points=points,
        config=_config(threshold_price=600.0),
        now=later,
    )
    assert fired_second == []

    # after the cooldown window, it fires again
    much_later = now + timedelta(hours=13)
    fired_third = decide_alert(
        conn,
        route_key="route-a",
        points=points,
        config=_config(threshold_price=600.0),
        now=much_later,
    )
    assert fired_third


def test_decide_alert_no_reasons_returns_empty(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    points = _points(1000.0, 999.0)
    config = _config(threshold_price=1.0, drop_percent=99, notify_on_new_low=False)
    fired = decide_alert(conn, route_key="route-a", points=points, config=config)
    assert fired == []
    assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0


def test_failed_send_does_not_consume_cooldown(tmp_path) -> None:
    """The whole point of splitting decide/record: if notifier.send() fails,
    the caller must not call record_alert_sent, so the SAME trigger fires
    again on the very next poll instead of being silently eaten for
    cooldown_hours.
    """
    conn = init_db(tmp_path / "skytracer.db")
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    points = _points(1000.0, 500.0)
    config = _config(threshold_price=600.0)

    fired = decide_alert(conn, route_key="route-a", points=points, config=config, now=now)
    assert fired
    # simulate a failed send: caller does NOT call record_alert_sent

    ten_seconds_later = now + timedelta(seconds=10)
    fired_again = decide_alert(
        conn, route_key="route-a", points=points, config=config, now=ten_seconds_later
    )
    assert fired_again == fired
