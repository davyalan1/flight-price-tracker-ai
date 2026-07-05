from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from skytracer import cli

REPO_ROOT = Path(__file__).parent.parent
runner = CliRunner()


def _env(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    shutil.copy(REPO_ROOT / "config.example.toml", config_path)
    monkeypatch.setenv("SKYTRACER_CONFIG", str(config_path))
    monkeypatch.setenv("SKYTRACER_DB", str(tmp_path / "skytracer.db"))


def test_poll_runs_when_never_polled_before(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    called = {"ran": False}
    monkeypatch.setattr(cli, "run_poll_once", lambda conn: called.__setitem__("ran", True))

    result = runner.invoke(cli.app, ["poll"])

    assert result.exit_code == 0
    assert called["ran"] is True


def test_poll_skips_when_not_due(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    called = {"ran": False}
    monkeypatch.setattr(cli, "is_poll_due", lambda conn, config: False)
    monkeypatch.setattr(cli, "run_poll_once", lambda conn: called.__setitem__("ran", True))

    result = runner.invoke(cli.app, ["poll"])

    assert result.exit_code == 0
    assert called["ran"] is False


def test_poll_force_ignores_schedule(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    called = {"ran": False}
    monkeypatch.setattr(cli, "is_poll_due", lambda conn, config: False)
    monkeypatch.setattr(cli, "run_poll_once", lambda conn: called.__setitem__("ran", True))

    result = runner.invoke(cli.app, ["poll", "--force"])

    assert result.exit_code == 0
    assert called["ran"] is True


def test_show_prints_no_observations_message(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    result = runner.invoke(cli.app, ["show"])
    assert result.exit_code == 0
    assert "No observations yet" in result.stdout


def test_show_prints_route_stats(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    from skytracer.db import init_db
    from skytracer.models import FareResult, SearchQuery
    from skytracer.observations import insert_observation

    conn = init_db(tmp_path / "skytracer.db")
    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-12-14",
        return_date="2027-01-08",
        adults=1,
        cabin="economy",
        currency="USD",
    )
    result_fare = FareResult(
        price=1500.0,
        currency="USD",
        airlines=["ANA"],
        stops=1,
        duration_min=600,
        route="OKC → NRT",
        source="google",
    )
    insert_observation(conn, route_key="OKC-NRT-test", query=query, result=result_fare)
    conn.close()

    result = runner.invoke(cli.app, ["show"])
    assert result.exit_code == 0
    assert "OKC-NRT-test" in result.stdout
    assert "1500.00" in result.stdout


def test_force_flag_bypasses_due_check_end_to_end(tmp_path, monkeypatch) -> None:
    """Not-mocked is_poll_due, real settings_store — confirms --force actually
    overrides a real 'already polled recently' state, not just a mocked one.
    """
    _env(tmp_path, monkeypatch)
    from datetime import UTC, datetime

    from skytracer.bootstrap import ensure_seeded
    from skytracer.db import init_db
    from skytracer.poller import LAST_POLL_AT_KEY
    from skytracer.settings_store import set as set_setting

    conn = init_db(tmp_path / "skytracer.db")
    ensure_seeded(conn)
    set_setting(conn, LAST_POLL_AT_KEY, datetime.now(UTC).isoformat())
    conn.close()

    called = {"ran": False}
    monkeypatch.setattr(cli, "run_poll_once", lambda conn: called.__setitem__("ran", True))

    result = runner.invoke(cli.app, ["poll"])
    assert called["ran"] is False  # just polled a moment ago, not due yet

    result = runner.invoke(cli.app, ["poll", "--force"])
    assert result.exit_code == 0
    assert called["ran"] is True
