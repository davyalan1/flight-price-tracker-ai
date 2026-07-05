from __future__ import annotations

import dataclasses

from skytracer.config import validate
from skytracer.db import init_db
from skytracer.settings_store import (
    as_dict,
    flatten,
    get,
    mask_secrets,
    seed_if_empty,
    set,
    unflatten,
)


def test_flatten_unflatten_round_trip() -> None:
    nested = {"a": {"b": 1, "c": "x"}, "d": True}
    flat = flatten(nested)
    assert flat == {"a.b": "1", "a.c": '"x"', "d": "true"}
    assert unflatten(flat) == nested


def test_seed_then_round_trip(tmp_path, valid_raw_config: dict) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    result = validate(valid_raw_config)

    seeded = seed_if_empty(conn, result.config)
    assert seeded is True

    restored = as_dict(conn)
    assert restored == dataclasses.asdict(result.config)


def test_seed_is_noop_when_not_empty(tmp_path, valid_raw_config: dict) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    result = validate(valid_raw_config)
    assert seed_if_empty(conn, result.config) is True

    set(conn, "trip.origin", "DFW")
    assert seed_if_empty(conn, result.config) is False
    assert get(conn, "trip.origin") == "DFW"


def test_get_set(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    assert get(conn, "trip.origin") is None
    assert get(conn, "trip.origin", "OKC") == "OKC"

    set(conn, "trip.origin", "OKC")
    assert get(conn, "trip.origin") == "OKC"

    set(conn, "trip.origin", "DFW")
    assert get(conn, "trip.origin") == "DFW"


def test_mask_secrets_hides_configured_values() -> None:
    d = {
        "sources": {"kiwi": {"enabled": True, "api_key": "super-secret"}},
        "web": {"admin_password": "hunter2"},
        "notify": {"whatsapp": {"phone": "+14055551234"}},
    }
    masked = mask_secrets(d)
    assert masked["sources"]["kiwi"]["api_key"] == "•••• set"
    assert masked["web"]["admin_password"] == "•••• set"
    # non-secret fields untouched
    assert masked["notify"]["whatsapp"]["phone"] == "+14055551234"
    assert masked["sources"]["kiwi"]["enabled"] is True


def test_mask_secrets_leaves_empty_secrets_empty() -> None:
    d = {"sources": {"kiwi": {"api_key": ""}}}
    masked = mask_secrets(d)
    assert masked["sources"]["kiwi"]["api_key"] == ""


def test_mask_secrets_does_not_mutate_input() -> None:
    d = {"web": {"admin_password": "hunter2"}}
    mask_secrets(d)
    assert d["web"]["admin_password"] == "hunter2"
