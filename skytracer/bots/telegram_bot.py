"""Thin wiring around python-telegram-bot: long-polling (no public webhook
needed), one allowlisted user, delegates all actual logic to bots.dispatch.
"""

from __future__ import annotations

import logging

from skytracer.bots import dispatch, is_allowed
from skytracer.config import AiConfig
from skytracer.db import init_db
from skytracer.paths import resolve_db_path

logger = logging.getLogger("skytracer.bots.telegram")


def run(ai_config: AiConfig) -> None:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters

    conn = init_db(resolve_db_path())

    async def on_message(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.text is None:
            return
        sender_id = message.from_user.id if message.from_user else None
        if not is_allowed(sender_id, ai_config.telegram_allowed_user_id):
            logger.warning("telegram: ignoring message from disallowed user %s", sender_id)
            return
        reply = dispatch(conn, ai_config, message.text)
        await message.reply_text(reply)

    application = Application.builder().token(ai_config.telegram_bot_token).build()
    application.add_handler(MessageHandler(filters.TEXT, on_message))
    logger.info("telegram: bot started, long-polling for messages")
    application.run_polling()
