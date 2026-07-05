"""Fare source adapters. Each source implements the FareSource protocol so
sources are swappable and individually toggleable from the settings table.
"""

from __future__ import annotations

from typing import Protocol

from skytracer.models import FareResult, SearchQuery


class FareSource(Protocol):
    name: str
    enabled: bool
    requires_key: bool

    def search(self, q: SearchQuery) -> list[FareResult]: ...

    def health_check(self) -> bool: ...
