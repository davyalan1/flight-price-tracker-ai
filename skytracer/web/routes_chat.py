"""The floating chat widget's backend — same dispatch logic as the
Telegram/Discord bots (/status, /lowest, or an LLM fallback), gated behind
the Settings login rather than a per-platform allowlist, since this is
reachable at whatever public URL the dashboard is deployed at.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from skytracer.bots import dispatch
from skytracer.settings_store import as_config
from skytracer.web.deps import SettingsConnDep

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(max_length=2000)


@router.post("/chat")
def chat(body: ChatRequest, conn: SettingsConnDep) -> dict[str, str]:
    config = as_config(conn)
    return {"reply": dispatch(conn, config.ai, body.message)}
