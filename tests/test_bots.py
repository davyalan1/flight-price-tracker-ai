from __future__ import annotations

from skytracer.bots import dispatch, is_allowed
from skytracer.bots.replies import lowest_reply, status_reply
from skytracer.db import init_db
from skytracer.models import FareResult, SearchQuery
from skytracer.observations import insert_observation
from tests.conftest import default_ai_config


def test_is_allowed_requires_a_configured_id_and_an_exact_match() -> None:
    assert is_allowed("123", "123") is True
    assert is_allowed("123", "456") is False
    assert is_allowed("123", "") is False  # empty allowlist must reject, not wildcard-allow
    assert is_allowed(123, "123") is True  # int sender id (Telegram/Discord both use ints)


def test_status_reply_and_lowest_reply_with_no_data(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    assert "hasn't run" in status_reply(conn)
    assert "hasn't run" in lowest_reply(conn)


def test_status_reply_and_lowest_reply_with_data(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    query = SearchQuery(
        origin="OKC", destination="NRT", depart_date="2026-09-01", return_date="2026-09-11",
        adults=1, cabin="economy", currency="USD",
    )
    prices = [(1500.0, "2026-01-01T00:00:00+00:00"), (1200.0, "2026-01-02T00:00:00+00:00")]
    for price, observed_at in prices:
        insert_observation(
            conn, route_key="OKC-NRT", query=query,
            result=FareResult(
                price=price, currency="USD", airlines=["ANA"], stops=1,
                duration_min=600, route="OKC → NRT", source="google",
            ),
            observed_at=observed_at,
        )

    status = status_reply(conn)
    assert "OKC-NRT" in status
    assert "1200.00" in status
    assert "↓" in status  # price dropped from 1500 to 1200

    lowest = lowest_reply(conn)
    assert "1200.00" in lowest  # all-time low


def test_dispatch_routes_status_and_lowest_without_touching_the_llm(
    tmp_path, monkeypatch
) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    ai_config = default_ai_config()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("answer_question should not be called for /status or /lowest")

    monkeypatch.setattr("skytracer.bots.answer_question", fail_if_called)

    assert dispatch(conn, ai_config, "/status") == status_reply(conn)
    assert dispatch(conn, ai_config, "/STATUS") == status_reply(conn)  # case-insensitive
    assert dispatch(conn, ai_config, "/lowest") == lowest_reply(conn)


def test_dispatch_falls_through_to_the_llm_for_anything_else(tmp_path, monkeypatch) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    ai_config = default_ai_config()

    calls = []

    def fake_answer_question(conn_arg, config_arg, question):
        calls.append(question)
        return "a grounded answer"

    monkeypatch.setattr("skytracer.bots.answer_question", fake_answer_question)

    result = dispatch(conn, ai_config, "any price drops recently?")
    assert result == "a grounded answer"
    assert calls == ["any price drops recently?"]
