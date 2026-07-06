# Phase 12 — Dashboard chat widget + web search (2026-07-06)

David's ask: a floating chat widget on the dashboard itself (not just
Telegram/Discord), and give the AI a real web-search tool backed by his
self-hosted SearXNG instance (`http://searxng.homelab:8888`).

Clarified with David before building:

- **Access**: the widget is gated behind the Settings login. The dashboard
  is deliberately open/no-login by design, but this now runs a real LLM
  (local or cloud) and can trigger web searches — and the site is publicly
  reachable (`skytracer.davserv.xyz`), so an anonymous, unauthenticated
  "burn compute/API credits" surface would be a real cost/abuse risk that
  the read-only dashboard never had.
- **Search integration**: real tool-calling (the model decides when to
  search), not always-on prompt injection. This is a deliberate exception
  to Phase 11's "avoid tool-calling, small local models are unreliable at
  it" stance — justified here because web search is genuinely open-ended
  (you can't pre-fetch a query you don't know yet, unlike the fixed,
  enumerable flight-stats domain), and David explicitly chose this
  tradeoff knowing the reliability caveat.

## What got built

- `skytracer/ai/tools.py` — `search_web(base_url, query)` (real SearXNG
  JSON API call, `GET /search?q=...&format=json`), plus both tool-schema
  shapes: `OPENAI_TOOL_SCHEMA` (Ollama/llama-server) and
  `ANTHROPIC_TOOL_SCHEMA` (Anthropic) — genuinely different request
  shapes for the same tool, same reasoning as the earlier thinking-toggle
  split.
- `skytracer/ai/openai_compat.py` — a shared `chat_with_tools()` loop used
  by *both* `OllamaBackend` and `LlamaServerBackend`, since (unlike the
  thinking toggle) their tool-calling request/response shape is identical
  — verified empirically against a real llama-server instance before
  writing any code (tool call round-trip: model requests `search_web`,
  gets a result, answers). Capped at 3 rounds to avoid a runaway loop.
- `AnthropicBackend` gets its own tool loop (Anthropic's `tool_use`/
  `tool_result` content-block shape is different from OpenAI's
  `tool_calls`/role=`tool` shape).
- New `ai.searxng_base_url` config field — the tool is only offered to the
  model at all when this is set; blank (default) means no `tools` array is
  sent, so nothing changes for existing setups.
- `skytracer/web/routes_chat.py` — `POST /chat`, gated by the same
  `SettingsConnDep` login dependency as Settings, reusing `bots.dispatch()`
  (so `/status`/`/lowest` still get exact templated replies, anything else
  goes through the LLM — same logic as Telegram/Discord, just a new
  transport).
- A small floating widget in `base.html`, rendered only `{% if logged_in
  %}` — vanilla JS, no framework, matching the app's no-SPA philosophy.

## Real-world verification, before committing

- Raw tool-call round-trip against `athena.homelab:11435` (llama-server,
  qwen3.5): confirmed a `tool_calls` response, then confirmed sending the
  tool result back produces a correct final answer.
- Same round-trip through the actual `LlamaServerBackend` class (not raw
  httpx) — real SearXNG search, real question ("latest stable Python
  version"), correct grounded answer.
- Full app path (`dispatch()` → `answer_question()` → real backend): a
  flight-price question correctly says "no data" instead of hallucinating
  when the DB is empty; a non-flight question ("ramen near Narita")
  correctly triggers a real search and gives a genuinely useful answer.
- The widget itself, driven by a real (headless) browser via Playwright:
  login → open widget → send a message → real reply rendered. One
  transient `httpx.ConnectError` was hit against `athena.homelab` during
  this — confirmed it was a real, temporary network blip (not a code bug)
  by retrying the same raw call moments later successfully; also confirmed
  the graceful-fallback hardening from the post-Phase-11 work handled it
  correctly (friendly message, not a crash) rather than actually needing a
  fix here.
