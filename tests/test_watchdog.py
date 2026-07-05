from __future__ import annotations

from skytracer.db import init_db
from skytracer.watchdog import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    is_broken,
    record_failure,
    record_success,
)


def test_record_failure_increments(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    assert record_failure(conn) == 1
    assert record_failure(conn) == 2
    assert record_failure(conn) == 3


def test_record_success_resets_counter(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    record_failure(conn)
    record_failure(conn)
    record_success(conn)
    assert record_failure(conn) == 1


def test_is_broken_threshold() -> None:
    assert is_broken(CONSECUTIVE_FAILURE_THRESHOLD - 1) is False
    assert is_broken(CONSECUTIVE_FAILURE_THRESHOLD) is True
    assert is_broken(CONSECUTIVE_FAILURE_THRESHOLD + 1) is True


def test_is_broken_custom_threshold() -> None:
    assert is_broken(5, threshold=10) is False
    assert is_broken(10, threshold=10) is True
