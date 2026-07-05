"""Config seed loading and validation.

The TOML file is only ever read to *seed* the settings table on first boot
(see settings_store.seed_if_empty). This module is pure: it turns a raw
parsed-TOML dict into a validated Config, or raises ConfigError with
human-readable messages. It never touches the database or the filesystem
beyond `load_toml`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

IATA_RE = re.compile(r"^[A-Z]{3}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
CABIN_CHOICES = {"economy", "premium_economy", "business", "first"}
NOTIFY_CHANNELS = {"whatsapp", "ntfy", "discord", "email"}
WHATSAPP_PROVIDERS = {"callmebot", "cloud_api", "twilio"}


class ConfigError(Exception):
    """Raised with one or more human-readable, field-specific messages."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


@dataclass
class FixedTrip:
    enabled: bool
    depart_date: str
    return_date: str


@dataclass
class FlexibleTrip:
    enabled: bool
    earliest_depart: str
    latest_depart: str
    trip_length_days: int
    scan_step_days: int


@dataclass
class TripConfig:
    origin: str
    destination: str
    adults: int
    cabin: str
    currency: str
    fixed: FixedTrip
    flexible: FlexibleTrip


@dataclass
class AlertsConfig:
    threshold_price: float
    drop_percent: float
    notify_on_new_low: bool
    cooldown_hours: float


@dataclass
class ScheduleConfig:
    every_hours: float


@dataclass
class GoogleSourceConfig:
    enabled: bool
    use_browser_fallback: bool


@dataclass
class KiwiSourceConfig:
    enabled: bool
    api_key: str


@dataclass
class TravelpayoutsSourceConfig:
    enabled: bool
    token: str


@dataclass
class DuffelSourceConfig:
    enabled: bool
    api_key: str


@dataclass
class McpSourceConfig:
    enabled: bool
    endpoint: str
    tool_name: str


@dataclass
class SourcesConfig:
    google: GoogleSourceConfig
    kiwi: KiwiSourceConfig
    travelpayouts: TravelpayoutsSourceConfig
    duffel: DuffelSourceConfig
    mcp: McpSourceConfig


@dataclass
class WhatsappNotifyConfig:
    provider: str
    phone: str
    callmebot_apikey: str
    # cloud_api / twilio are upgrade paths behind the same provider switch —
    # see notify/whatsapp.py for the template-approval caveat.
    cloud_api_phone_number_id: str = ""
    cloud_api_access_token: str = ""
    cloud_api_template_name: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""


@dataclass
class NtfyNotifyConfig:
    server: str
    topic: str


@dataclass
class DiscordNotifyConfig:
    webhook_url: str


@dataclass
class EmailNotifyConfig:
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    to_addr: str


@dataclass
class NotifyConfig:
    channel: str
    whatsapp: WhatsappNotifyConfig
    ntfy: NtfyNotifyConfig
    discord: DiscordNotifyConfig
    email: EmailNotifyConfig


@dataclass
class DashboardConfig:
    top_n_fares: int


AI_PROVIDERS = {"ollama", "anthropic"}


@dataclass
class AiConfig:
    provider: str
    ollama_base_url: str
    ollama_model: str
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_allowed_user_id: str
    discord_bot_token: str
    discord_allowed_user_id: str


@dataclass
class WebConfig:
    host: str
    port: int
    admin_password: str


@dataclass
class DbConfig:
    path: str


@dataclass
class Config:
    trip: TripConfig
    alerts: AlertsConfig
    schedule: ScheduleConfig
    sources: SourcesConfig
    notify: NotifyConfig
    dashboard: DashboardConfig
    ai: AiConfig
    web: WebConfig
    db: DbConfig


@dataclass
class ValidationResult:
    config: Config
    warnings: list[str]


def load_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _iso_date(value: str, field: str, errors: list[str]) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"'{field}' value '{value}' isn't a valid date (use YYYY-MM-DD).")


def validate(raw: dict) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    trip_raw = raw.get("trip", {})
    origin = str(trip_raw.get("origin", ""))
    destination = str(trip_raw.get("destination", ""))
    if not IATA_RE.match(origin):
        errors.append(
            f"'{origin}' isn't a 3-letter IATA airport code for trip.origin "
            "(e.g. OKC for Oklahoma City)."
        )
    if not IATA_RE.match(destination):
        errors.append(
            f"'{destination}' isn't a 3-letter IATA airport code for trip.destination "
            "(e.g. NRT for Narita, HND for Haneda)."
        )

    adults = trip_raw.get("adults", 1)
    if not isinstance(adults, int) or adults < 1:
        errors.append(f"trip.adults must be a positive whole number, got '{adults}'.")

    cabin = str(trip_raw.get("cabin", ""))
    if cabin not in CABIN_CHOICES:
        errors.append(
            f"'{cabin}' isn't a valid trip.cabin — choose one of: "
            f"{', '.join(sorted(CABIN_CHOICES))}."
        )

    currency = str(trip_raw.get("currency", ""))
    if not CURRENCY_RE.match(currency):
        errors.append(f"'{currency}' isn't a 3-letter currency code for trip.currency (e.g. USD).")

    fixed_raw = trip_raw.get("fixed", {})
    flexible_raw = trip_raw.get("flexible", {})
    fixed_enabled = bool(fixed_raw.get("enabled", False))
    flexible_enabled = bool(flexible_raw.get("enabled", False))
    if fixed_enabled == flexible_enabled:
        errors.append(
            "Enable exactly one of trip.fixed or trip.flexible (currently "
            f"{'both' if fixed_enabled else 'neither'} enabled)."
        )

    depart_date = str(fixed_raw.get("depart_date", ""))
    return_date = str(fixed_raw.get("return_date", ""))
    if fixed_enabled:
        if not depart_date:
            errors.append("trip.fixed.depart_date is required when trip.fixed is enabled.")
        else:
            _iso_date(depart_date, "trip.fixed.depart_date", errors)
        if return_date:
            _iso_date(return_date, "trip.fixed.return_date", errors)
            if depart_date and return_date and not errors and return_date < depart_date:
                errors.append("trip.fixed.return_date can't be before trip.fixed.depart_date.")

    earliest_depart = str(flexible_raw.get("earliest_depart", ""))
    latest_depart = str(flexible_raw.get("latest_depart", ""))
    trip_length_days = flexible_raw.get("trip_length_days", 0)
    scan_step_days = flexible_raw.get("scan_step_days", 0)
    if flexible_enabled:
        if not earliest_depart:
            errors.append(
                "trip.flexible.earliest_depart is required when trip.flexible is enabled."
            )
        else:
            _iso_date(earliest_depart, "trip.flexible.earliest_depart", errors)
        if not latest_depart:
            errors.append(
                "trip.flexible.latest_depart is required when trip.flexible is enabled."
            )
        else:
            _iso_date(latest_depart, "trip.flexible.latest_depart", errors)
        if (
            earliest_depart
            and latest_depart
            and not errors
            and latest_depart < earliest_depart
        ):
            errors.append(
                "trip.flexible.latest_depart can't be before trip.flexible.earliest_depart."
            )
        if not isinstance(trip_length_days, int) or trip_length_days < 1:
            errors.append(
                f"trip.flexible.trip_length_days must be a positive whole number, "
                f"got '{trip_length_days}'."
            )
        if not isinstance(scan_step_days, int) or scan_step_days < 1:
            errors.append(
                f"trip.flexible.scan_step_days must be a positive whole number, "
                f"got '{scan_step_days}'."
            )

    alerts_raw = raw.get("alerts", {})
    threshold_price = alerts_raw.get("threshold_price", 0)
    drop_percent = alerts_raw.get("drop_percent", 0)
    cooldown_hours = alerts_raw.get("cooldown_hours", 0)
    notify_on_new_low = bool(alerts_raw.get("notify_on_new_low", True))
    if not isinstance(threshold_price, int | float) or threshold_price <= 0:
        errors.append(f"alerts.threshold_price must be a positive number, got '{threshold_price}'.")
    if not isinstance(drop_percent, int | float) or not (0 <= drop_percent <= 100):
        errors.append(f"alerts.drop_percent must be between 0 and 100, got '{drop_percent}'.")
    if not isinstance(cooldown_hours, int | float) or cooldown_hours < 0:
        errors.append(
            f"alerts.cooldown_hours must be zero or a positive number, got '{cooldown_hours}'."
        )

    schedule_raw = raw.get("schedule", {})
    every_hours = schedule_raw.get("every_hours", 0)
    if not isinstance(every_hours, int | float) or every_hours <= 0:
        errors.append(f"schedule.every_hours must be a positive number, got '{every_hours}'.")

    sources_raw = raw.get("sources", {})
    google_raw = sources_raw.get("google", {})
    kiwi_raw = sources_raw.get("kiwi", {})
    travelpayouts_raw = sources_raw.get("travelpayouts", {})
    duffel_raw = sources_raw.get("duffel", {})
    mcp_raw = sources_raw.get("mcp", {})

    kiwi_enabled = bool(kiwi_raw.get("enabled", False))
    kiwi_api_key = str(kiwi_raw.get("api_key", ""))
    if kiwi_enabled and not kiwi_api_key:
        errors.append(
            "sources.kiwi is enabled but api_key is empty — paste a key on the "
            "Settings page or disable this source."
        )

    travelpayouts_enabled = bool(travelpayouts_raw.get("enabled", False))
    travelpayouts_token = str(travelpayouts_raw.get("token", ""))
    if travelpayouts_enabled and not travelpayouts_token:
        errors.append(
            "sources.travelpayouts is enabled but token is empty — paste a token on "
            "the Settings page or disable this source."
        )

    duffel_enabled = bool(duffel_raw.get("enabled", False))
    duffel_api_key = str(duffel_raw.get("api_key", ""))
    if duffel_enabled and not duffel_api_key:
        errors.append(
            "sources.duffel is enabled but api_key is empty — paste a key on the "
            "Settings page or disable this source."
        )

    mcp_enabled = bool(mcp_raw.get("enabled", False))
    mcp_endpoint = str(mcp_raw.get("endpoint", ""))
    mcp_tool_name = str(mcp_raw.get("tool_name", "") or "search_flights")
    if mcp_enabled and not mcp_endpoint:
        errors.append(
            "sources.mcp is enabled but endpoint is empty — set an endpoint on the "
            "Settings page or disable this source."
        )

    notify_raw = raw.get("notify", {})
    channel = str(notify_raw.get("channel", ""))
    if channel not in NOTIFY_CHANNELS:
        errors.append(
            f"'{channel}' isn't a valid notify.channel — choose one of: "
            f"{', '.join(sorted(NOTIFY_CHANNELS))}."
        )

    whatsapp_raw = notify_raw.get("whatsapp", {})
    provider = str(whatsapp_raw.get("provider", "callmebot"))
    if provider not in WHATSAPP_PROVIDERS:
        errors.append(
            f"'{provider}' isn't a valid notify.whatsapp.provider — choose one of: "
            f"{', '.join(sorted(WHATSAPP_PROVIDERS))}."
        )
    whatsapp_phone = str(whatsapp_raw.get("phone", ""))
    whatsapp_apikey = str(whatsapp_raw.get("callmebot_apikey", ""))
    whatsapp_cloud_api_phone_number_id = str(whatsapp_raw.get("cloud_api_phone_number_id", ""))
    whatsapp_cloud_api_access_token = str(whatsapp_raw.get("cloud_api_access_token", ""))
    whatsapp_cloud_api_template_name = str(whatsapp_raw.get("cloud_api_template_name", ""))
    whatsapp_twilio_account_sid = str(whatsapp_raw.get("twilio_account_sid", ""))
    whatsapp_twilio_auth_token = str(whatsapp_raw.get("twilio_auth_token", ""))
    whatsapp_twilio_from_number = str(whatsapp_raw.get("twilio_from_number", ""))

    ntfy_raw = notify_raw.get("ntfy", {})
    ntfy_server = str(ntfy_raw.get("server", "https://ntfy.sh"))
    ntfy_topic = str(ntfy_raw.get("topic", ""))

    discord_raw = notify_raw.get("discord", {})
    discord_webhook = str(discord_raw.get("webhook_url", ""))

    email_raw = notify_raw.get("email", {})
    email_smtp_host = str(email_raw.get("smtp_host", ""))
    email_smtp_port = email_raw.get("smtp_port", 587)
    email_username = str(email_raw.get("username", ""))
    email_password = str(email_raw.get("password", ""))
    email_to_addr = str(email_raw.get("to_addr", ""))
    if not isinstance(email_smtp_port, int) or not (1 <= email_smtp_port <= 65535):
        errors.append(
            f"notify.email.smtp_port must be a valid port number, got '{email_smtp_port}'."
        )

    # Operational-readiness gaps (missing notification target) are warnings,
    # not hard failures — a fresh install has nothing configured yet.
    whatsapp_ready = whatsapp_phone and whatsapp_apikey
    if channel == "whatsapp" and provider == "callmebot" and not whatsapp_ready:
        warnings.append(
            "notify.whatsapp is selected but phone/callmebot_apikey aren't set yet — "
            "alerts won't be deliverable until this is filled in on the Settings page."
        )
    if channel == "ntfy" and not ntfy_topic:
        warnings.append(
            "notify.ntfy is selected but topic is empty — set one on the Settings page."
        )
    if channel == "discord" and not discord_webhook:
        warnings.append(
            "notify.discord is selected but webhook_url is empty — set one on the Settings page."
        )
    if channel == "email" and not (email_smtp_host and email_to_addr):
        warnings.append(
            "notify.email is selected but smtp_host/to_addr aren't set yet — set them on "
            "the Settings page."
        )

    dashboard_raw = raw.get("dashboard", {})
    top_n_fares = dashboard_raw.get("top_n_fares", 5)
    if not isinstance(top_n_fares, int) or not (1 <= top_n_fares <= 10):
        errors.append(
            f"dashboard.top_n_fares must be a whole number from 1-10, got '{top_n_fares}'."
        )

    ai_raw = raw.get("ai", {})
    ai_provider = str(ai_raw.get("provider", "ollama"))
    if ai_provider not in AI_PROVIDERS:
        errors.append(
            f"'{ai_provider}' isn't a valid ai.provider — choose one of: "
            f"{', '.join(sorted(AI_PROVIDERS))}."
        )
    ai_ollama_base_url = str(ai_raw.get("ollama_base_url", "http://localhost:11434/v1"))
    ai_ollama_model = str(ai_raw.get("ollama_model", "llama3"))
    ai_anthropic_api_key = str(ai_raw.get("anthropic_api_key", ""))
    if ai_provider == "anthropic" and not ai_anthropic_api_key:
        warnings.append(
            "ai.provider is 'anthropic' but anthropic_api_key is empty — the chat bots "
            "won't be able to answer until it's set on the Settings page."
        )
    ai_telegram_bot_token = str(ai_raw.get("telegram_bot_token", ""))
    ai_telegram_allowed_user_id = str(ai_raw.get("telegram_allowed_user_id", ""))
    if ai_telegram_bot_token and not ai_telegram_allowed_user_id:
        warnings.append(
            "ai.telegram_bot_token is set but telegram_allowed_user_id is empty — the bot "
            "won't reply to anyone until an allowed user ID is set."
        )
    ai_discord_bot_token = str(ai_raw.get("discord_bot_token", ""))
    ai_discord_allowed_user_id = str(ai_raw.get("discord_allowed_user_id", ""))
    if ai_discord_bot_token and not ai_discord_allowed_user_id:
        warnings.append(
            "ai.discord_bot_token is set but discord_allowed_user_id is empty — the bot "
            "won't reply to anyone until an allowed user ID is set."
        )

    web_raw = raw.get("web", {})
    host = str(web_raw.get("host", "0.0.0.0"))
    port = web_raw.get("port", 8087)
    admin_password = str(web_raw.get("admin_password", ""))
    if not isinstance(port, int) or not (1 <= port <= 65535):
        errors.append(f"web.port must be a valid port number, got '{port}'.")
    if not admin_password:
        warnings.append(
            "web.admin_password is empty — the first visit to /settings will require "
            "creating one."
        )

    db_raw = raw.get("db", {})
    db_path = str(db_raw.get("path", ""))
    if not db_path:
        errors.append("db.path is required.")

    if errors:
        raise ConfigError(errors)

    config = Config(
        trip=TripConfig(
            origin=origin,
            destination=destination,
            adults=adults,
            cabin=cabin,
            currency=currency,
            fixed=FixedTrip(
                enabled=fixed_enabled, depart_date=depart_date, return_date=return_date
            ),
            flexible=FlexibleTrip(
                enabled=flexible_enabled,
                earliest_depart=earliest_depart,
                latest_depart=latest_depart,
                trip_length_days=trip_length_days,
                scan_step_days=scan_step_days,
            ),
        ),
        alerts=AlertsConfig(
            threshold_price=threshold_price,
            drop_percent=drop_percent,
            notify_on_new_low=notify_on_new_low,
            cooldown_hours=cooldown_hours,
        ),
        schedule=ScheduleConfig(every_hours=every_hours),
        sources=SourcesConfig(
            google=GoogleSourceConfig(
                enabled=bool(google_raw.get("enabled", True)),
                use_browser_fallback=bool(google_raw.get("use_browser_fallback", True)),
            ),
            kiwi=KiwiSourceConfig(enabled=kiwi_enabled, api_key=kiwi_api_key),
            travelpayouts=TravelpayoutsSourceConfig(
                enabled=travelpayouts_enabled, token=travelpayouts_token
            ),
            duffel=DuffelSourceConfig(enabled=duffel_enabled, api_key=duffel_api_key),
            mcp=McpSourceConfig(
                enabled=mcp_enabled, endpoint=mcp_endpoint, tool_name=mcp_tool_name
            ),
        ),
        notify=NotifyConfig(
            channel=channel,
            whatsapp=WhatsappNotifyConfig(
                provider=provider,
                phone=whatsapp_phone,
                callmebot_apikey=whatsapp_apikey,
                cloud_api_phone_number_id=whatsapp_cloud_api_phone_number_id,
                cloud_api_access_token=whatsapp_cloud_api_access_token,
                cloud_api_template_name=whatsapp_cloud_api_template_name,
                twilio_account_sid=whatsapp_twilio_account_sid,
                twilio_auth_token=whatsapp_twilio_auth_token,
                twilio_from_number=whatsapp_twilio_from_number,
            ),
            ntfy=NtfyNotifyConfig(server=ntfy_server, topic=ntfy_topic),
            discord=DiscordNotifyConfig(webhook_url=discord_webhook),
            email=EmailNotifyConfig(
                smtp_host=email_smtp_host,
                smtp_port=email_smtp_port,
                username=email_username,
                password=email_password,
                to_addr=email_to_addr,
            ),
        ),
        dashboard=DashboardConfig(top_n_fares=top_n_fares),
        ai=AiConfig(
            provider=ai_provider,
            ollama_base_url=ai_ollama_base_url,
            ollama_model=ai_ollama_model,
            anthropic_api_key=ai_anthropic_api_key,
            telegram_bot_token=ai_telegram_bot_token,
            telegram_allowed_user_id=ai_telegram_allowed_user_id,
            discord_bot_token=ai_discord_bot_token,
            discord_allowed_user_id=ai_discord_allowed_user_id,
        ),
        web=WebConfig(host=host, port=port, admin_password=admin_password),
        db=DbConfig(path=db_path),
    )
    return ValidationResult(config=config, warnings=warnings)


def load_and_validate(path: str | Path) -> ValidationResult:
    return validate(load_toml(path))


def build_config(raw: dict) -> Config:
    """Reconstruct a typed Config from a nested dict shaped like
    dataclasses.asdict(Config(...)) — i.e. what settings_store.as_dict()
    returns. Unlike validate(), this assumes the data is already valid
    (it came from the settings table, which is seeded/edited through
    validated paths) and does no error checking.
    """
    trip_raw = raw["trip"]
    sources_raw = raw["sources"]
    notify_raw = raw["notify"]
    return Config(
        trip=TripConfig(
            origin=trip_raw["origin"],
            destination=trip_raw["destination"],
            adults=trip_raw["adults"],
            cabin=trip_raw["cabin"],
            currency=trip_raw["currency"],
            fixed=FixedTrip(**trip_raw["fixed"]),
            flexible=FlexibleTrip(**trip_raw["flexible"]),
        ),
        alerts=AlertsConfig(**raw["alerts"]),
        schedule=ScheduleConfig(**raw["schedule"]),
        sources=SourcesConfig(
            google=GoogleSourceConfig(**sources_raw["google"]),
            kiwi=KiwiSourceConfig(**sources_raw["kiwi"]),
            travelpayouts=TravelpayoutsSourceConfig(**sources_raw["travelpayouts"]),
            duffel=DuffelSourceConfig(**sources_raw["duffel"]),
            mcp=McpSourceConfig(**sources_raw["mcp"]),
        ),
        notify=NotifyConfig(
            channel=notify_raw["channel"],
            whatsapp=WhatsappNotifyConfig(**notify_raw["whatsapp"]),
            ntfy=NtfyNotifyConfig(**notify_raw["ntfy"]),
            discord=DiscordNotifyConfig(**notify_raw["discord"]),
            email=EmailNotifyConfig(**notify_raw["email"]),
        ),
        dashboard=DashboardConfig(**raw["dashboard"]),
        ai=AiConfig(**raw["ai"]),
        web=WebConfig(**raw["web"]),
        db=DbConfig(**raw["db"]),
    )
