from __future__ import annotations

import pytest

from skytracer.config import ConfigError, validate


def test_valid_config_passes(valid_raw_config: dict) -> None:
    result = validate(valid_raw_config)
    assert result.config.trip.origin == "OKC"
    assert result.config.trip.destination == "NRT"
    assert result.config.trip.flexible.enabled is True
    assert result.config.trip.fixed.enabled is False
    # whatsapp selected but phone/apikey empty -> readiness warning, not an error
    assert any("whatsapp" in w for w in result.warnings)
    assert result.config.dashboard.top_n_fares == 5


def test_top_n_fares_defaults_to_5_when_dashboard_section_missing(valid_raw_config: dict) -> None:
    del valid_raw_config["dashboard"]
    result = validate(valid_raw_config)
    assert result.config.dashboard.top_n_fares == 5


def test_top_n_fares_out_of_range_is_rejected(valid_raw_config: dict) -> None:
    valid_raw_config["dashboard"]["top_n_fares"] = 11
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("top_n_fares" in m for m in exc_info.value.messages)


def test_ai_defaults_to_ollama_when_ai_section_missing(valid_raw_config: dict) -> None:
    del valid_raw_config["ai"]
    result = validate(valid_raw_config)
    assert result.config.ai.provider == "ollama"
    assert result.config.ai.ollama_base_url == "http://localhost:11434/v1"


def test_ai_invalid_provider_is_rejected(valid_raw_config: dict) -> None:
    valid_raw_config["ai"]["provider"] = "chatgpt"
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("ai.provider" in m for m in exc_info.value.messages)


def test_ai_anthropic_without_key_warns_not_errors(valid_raw_config: dict) -> None:
    valid_raw_config["ai"]["provider"] = "anthropic"
    result = validate(valid_raw_config)
    assert any("anthropic_api_key" in w for w in result.warnings)


def test_ai_telegram_token_without_allowed_id_warns(valid_raw_config: dict) -> None:
    valid_raw_config["ai"]["telegram_bot_token"] = "123:abc"
    result = validate(valid_raw_config)
    assert any("telegram_allowed_user_id" in w for w in result.warnings)


def test_bad_iata_code(valid_raw_config: dict) -> None:
    valid_raw_config["trip"]["destination"] = "TOKYO"
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("TOKYO" in msg for msg in exc_info.value.messages)


def test_both_fixed_and_flexible_enabled(valid_raw_config: dict) -> None:
    valid_raw_config["trip"]["fixed"]["enabled"] = True
    valid_raw_config["trip"]["fixed"]["depart_date"] = "2026-10-01"
    valid_raw_config["trip"]["flexible"]["enabled"] = True
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("exactly one" in msg for msg in exc_info.value.messages)


def test_neither_fixed_nor_flexible_enabled(valid_raw_config: dict) -> None:
    valid_raw_config["trip"]["flexible"]["enabled"] = False
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("exactly one" in msg for msg in exc_info.value.messages)


def test_enabled_source_missing_key(valid_raw_config: dict) -> None:
    valid_raw_config["sources"]["kiwi"]["enabled"] = True
    valid_raw_config["sources"]["kiwi"]["api_key"] = ""
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("sources.kiwi" in msg for msg in exc_info.value.messages)


def test_enabled_source_with_key_is_fine(valid_raw_config: dict) -> None:
    valid_raw_config["sources"]["kiwi"]["enabled"] = True
    valid_raw_config["sources"]["kiwi"]["api_key"] = "test-key-123"
    result = validate(valid_raw_config)
    assert result.config.sources.kiwi.enabled is True
    assert result.config.sources.kiwi.api_key == "test-key-123"


def test_invalid_cabin_enum(valid_raw_config: dict) -> None:
    valid_raw_config["trip"]["cabin"] = "coach"
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("cabin" in msg for msg in exc_info.value.messages)


def test_invalid_notify_channel(valid_raw_config: dict) -> None:
    valid_raw_config["notify"]["channel"] = "carrier_pigeon"
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("notify.channel" in msg for msg in exc_info.value.messages)


def test_flexible_window_dates_reversed(valid_raw_config: dict) -> None:
    valid_raw_config["trip"]["flexible"]["earliest_depart"] = "2026-12-01"
    valid_raw_config["trip"]["flexible"]["latest_depart"] = "2026-09-01"
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("latest_depart" in msg for msg in exc_info.value.messages)


def test_negative_threshold_price(valid_raw_config: dict) -> None:
    valid_raw_config["alerts"]["threshold_price"] = -50
    with pytest.raises(ConfigError) as exc_info:
        validate(valid_raw_config)
    assert any("threshold_price" in msg for msg in exc_info.value.messages)
