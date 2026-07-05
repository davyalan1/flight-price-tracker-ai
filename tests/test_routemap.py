from __future__ import annotations

from skytracer.routemap import coords_for, render_route_svg


def test_render_route_svg_draws_a_dot_per_known_airport() -> None:
    svg = render_route_svg(["OKC", "ORD", "NRT"])
    assert svg is not None
    assert svg.count("<circle") == 3
    assert "OKC" in svg and "NRT" in svg


def test_render_route_svg_returns_none_for_unknown_code() -> None:
    assert render_route_svg(["OKC", "ZZZ"]) is None


def test_render_route_svg_returns_none_for_fewer_than_two_codes() -> None:
    assert render_route_svg(["OKC"]) is None
    assert render_route_svg([]) is None


def test_coords_for_returns_lat_lon_per_code() -> None:
    coords = coords_for(["OKC", "NRT"])
    assert coords == [
        {"code": "OKC", "lat": 35.3931, "lon": -97.6007},
        {"code": "NRT", "lat": 35.7647, "lon": 140.3864},
    ]


def test_coords_for_returns_none_for_unknown_code() -> None:
    assert coords_for(["OKC", "ZZZ"]) is None
