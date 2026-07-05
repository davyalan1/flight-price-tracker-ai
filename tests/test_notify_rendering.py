from __future__ import annotations

from skytracer.models import Alert
from skytracer.notify.rendering import render_alert_message


def _alert(**overrides) -> Alert:
    base = dict(
        route_key="OKC-NRT-economy-test",
        route="OKC → DEN → NRT",
        price=1223.0,
        currency="USD",
        reasons=["threshold", "new_low"],
        all_time_low=1223.0,
        deep_link="https://www.google.com/travel/flights/search?tfs=abc",
        dashboard_url="http://localhost:8087/route/OKC-NRT-economy-test",
    )
    base.update(overrides)
    return Alert(**base)


def test_render_includes_route_price_and_reasons() -> None:
    message = render_alert_message(_alert())
    assert "OKC → DEN → NRT" in message
    assert "USD 1223.00" in message
    assert "threshold" in message
    assert "new low" in message  # underscores rendered as spaces


def test_render_includes_all_time_low() -> None:
    message = render_alert_message(_alert(all_time_low=999.0))
    assert "999.00" in message


def test_render_includes_deep_link_when_present() -> None:
    message = render_alert_message(_alert(deep_link="https://example.com/book"))
    assert "https://example.com/book" in message


def test_render_omits_deep_link_when_absent() -> None:
    message = render_alert_message(_alert(deep_link=None))
    assert "https://" not in message


def test_render_is_short_and_emoji_light() -> None:
    message = render_alert_message(_alert())
    # a handful of short lines, not a wall of text
    assert len(message.splitlines()) <= 4
