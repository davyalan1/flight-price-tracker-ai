"""Logging setup. Writes plain-formatted lines to stdout — journald timestamps
and captures them once this runs under systemd; no need to duplicate that here.
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format=_FORMAT, force=True)
    # httpx logs "HTTP Request: GET <full url incl. query string>" at INFO
    # on every request, successful or not. CallMeBot carries its apikey as
    # a query param, so at INFO this would log it on every successful send
    # — a broader leak than the one fixed in notify/_http.py, which only
    # covered the error-response path.
    logging.getLogger("httpx").setLevel(logging.WARNING)
