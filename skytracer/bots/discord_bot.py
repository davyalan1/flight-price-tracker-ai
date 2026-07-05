"""Thin wiring around discord.py: a persistent websocket connection (no
public endpoint needed), one allowlisted user, delegates all actual logic
to bots.dispatch.
"""

from __future__ import annotations

import logging

from skytracer.bots import dispatch, is_allowed
from skytracer.config import AiConfig
from skytracer.db import init_db
from skytracer.paths import resolve_db_path

logger = logging.getLogger("skytracer.bots.discord")


def run(ai_config: AiConfig) -> None:
    import discord

    conn = init_db(resolve_db_path())

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author == client.user:
            return
        if not is_allowed(message.author.id, ai_config.discord_allowed_user_id):
            logger.warning(
                "discord: ignoring message from disallowed user %s", message.author.id
            )
            return
        reply = dispatch(conn, ai_config, message.content)
        await message.channel.send(reply)

    logger.info("discord: bot starting, connecting to gateway")
    client.run(ai_config.discord_bot_token)
