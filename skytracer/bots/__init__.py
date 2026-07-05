"""Telegram/Discord conversational bot processes (Phase 11).

dispatch() is the one piece of logic shared by both platforms and the only
part worth unit-testing directly — the platform-specific modules
(telegram_bot.py, discord_bot.py) are thin wiring around a library's
message-received callback and stay untested at that layer, same as the
CLI-stub philosophy elsewhere in this app (Phase 1's cli.py).
"""

from __future__ import annotations

import logging
import sqlite3

from skytracer.ai.answer import answer_question
from skytracer.bots.replies import lowest_reply, status_reply
from skytracer.config import AiConfig

logger = logging.getLogger("skytracer.bots")


def is_allowed(sender_id: str, allowed_id: str) -> bool:
    """Single-user allowlist: an empty allowed_id means "well, don't reply to
    anyone" (misconfiguration), never "allow everyone" — the emptiness must
    be rejected, not treated as a wildcard.
    """
    return bool(allowed_id) and str(sender_id) == str(allowed_id)


def dispatch(conn: sqlite3.Connection, ai_config: AiConfig, text: str) -> str:
    """/status and /lowest get an exact, templated (non-LLM) answer; anything
    else falls through to the LLM, still grounded in the same real data.
    """
    command = text.strip().lower()
    if command == "/status":
        return status_reply(conn)
    if command == "/lowest":
        return lowest_reply(conn)
    try:
        return answer_question(conn, ai_config, text)
    except Exception:
        # Seen for real against a misbehaving local model server (empty
        # content, 200 OK) — never let a bad LLM response reach a bot's
        # send-message call as an empty string or an unhandled crash.
        logger.exception("dispatch: LLM backend failed to answer %r", text)
        return "Sorry, I couldn't get an answer just now — try /status or /lowest instead."
