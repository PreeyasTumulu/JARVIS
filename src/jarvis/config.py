"""Configuration: committed defaults, local overrides, and secrets from .env.

Load order (later wins): config/jarvis.toml, config/local.toml, explicit overrides.
Tables merge key by key, lists replace. Unknown keys are rejected so typos fail loudly.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.tools.base import Risk, Sensitivity

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """The configuration is missing or invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSettings(_Section):
    max_iterations: int = Field(default=6, ge=1, le=20)
    turn_timeout_s: float = Field(default=180, gt=0)
    tool_timeout_s: float = Field(default=20, gt=0)
    max_tool_calls_per_step: int = Field(default=4, ge=1)
    history_turns: int = Field(default=8, ge=0)
    max_tool_result_chars: int = Field(default=4000, ge=200)
    tool_routing: Literal["keywords", "all"] = "keywords"
    # When no keyword matches, pick tool groups by meaning with an embedding model (ADR-063).
    semantic_routing: bool = True
    semantic_model: str = "nomic-embed-text"
    semantic_threshold: float = Field(default=0.62, gt=0, lt=1)
    semantic_timeout_s: float = Field(default=2.0, gt=0)


class ProviderSettings(_Section):
    base_url: str
    model: str
    api_key_env: str = ""
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_s: float = Field(default=120, gt=0)
    max_tokens: int | None = Field(default=300, ge=16)  # caps rambling replies (and their wait)

    def api_key(self) -> str:
        """Return the API key from the environment, or a placeholder for keyless servers."""
        if not self.api_key_env:
            return "not-needed"  # Ollama ignores the key, but the client requires one
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ConfigError(
                f"Environment variable {self.api_key_env} is not set. Add it to .env "
                "(see .env.example)."
            )
        return key


class LLMSettings(_Section):
    default: str = "local"
    providers: dict[str, ProviderSettings]

    def active(self) -> ProviderSettings:
        try:
            return self.providers[self.default]
        except KeyError:
            raise ConfigError(
                f"llm.default is '{self.default}' but no [llm.providers.{self.default}] exists."
            ) from None


class RouterSettings(_Section):
    # Cloud providers from [llm.providers], tried in order for heavy questions that touch only
    # public data. A provider without its API key in .env is skipped; empty means local only.
    cloud: list[str] = []
    escalate: Literal["auto", "explicit", "never"] = "auto"
    daily_requests: dict[str, int] = {}  # per provider, to stay inside a free tier's daily limit
    cooldown_s: float = Field(default=300, gt=0)  # a provider that failed is skipped this long


class SafetySettings(_Section):
    app_allowlist: list[str] = []
    unlisted_apps: Literal["confirm", "block"] = "confirm"
    confirm_timeout_s: float = Field(default=30, gt=0)
    tool_risk_overrides: dict[str, Risk] = {}
    safe_to_close: list[str] = []
    # Apps where click, type_text, and press_keys run without asking (destructive targets still
    # ask). Messaging apps and terminals always ask, whatever this says (tools/ui/guard.py).
    trusted_ui_apps: list[str] = []


class AppsSettings(_Section):
    match_threshold: float = Field(default=75, ge=0, le=100)
    aliases: dict[str, str] = {}
    process_names: dict[str, str] = {}  # app name to executable, for matching open windows


class FilesSettings(_Section):
    allowed_folders: list[str] = ["{documents}", "{desktop}", "{downloads}"]
    blocked_patterns: list[str] = []
    blocked_extensions: list[str] = []
    confirm_extensions: list[str] = []
    skip_dirs: list[str] = []
    index_max_age_hours: float = Field(default=12, gt=0)
    max_indexed_files: int = Field(default=300_000, ge=1000)
    read_max_chars: int = Field(default=6000, ge=500)
    read_max_mb: float = Field(default=25, gt=0)
    everything: Literal["auto", "never"] = "auto"


class SearchSettings(_Section):
    max_results: int = Field(default=5, ge=1, le=10)
    region: str = "us-en"
    # Extra or changed sites for search_site: name to a search address with {q} (the query,
    # form encoded) or {p} (path encoded), e.g. {"amazon" = "https://www.amazon.com/s?k={q}"}.
    sites: dict[str, str] = {}


class WebSettings(_Section):
    fetch_max_chars: int = Field(default=6000, ge=500)  # page text the model gets to see
    fetch_max_mb: float = Field(default=3, gt=0)  # larger downloads are cut off


class MarketSettings(_Section):
    # Tried in order. Providers without an API key in .env are skipped; yfinance needs none.
    providers: list[Literal["finnhub", "twelvedata", "alphavantage", "yfinance"]] = [
        "finnhub",
        "twelvedata",
        "alphavantage",
        "yfinance",
    ]
    aliases: dict[str, str] = {}  # spoken name to ticker, for example "nifty" = "^NSEI"
    # When search finds the same company on one of these exchanges, use that listing
    # (Infosys on NSE, INFY.NS, rather than its US share, INFY).
    prefer_listings: list[str] = []
    crypto_currency: str = "USD"  # used when a crypto question names no currency


class WeatherSettings(_Section):
    home: str = ""  # your city, used when a question names no place
    units: Literal["celsius", "fahrenheit"] = "celsius"


class SystemSettings(_Section):
    screenshot_folder: str = "{pictures}/Screenshots"


class UISettings(_Section):
    read_max_chars: int = Field(default=6000, ge=500)  # window text the model gets to see
    window_wait_s: float = Field(default=10, gt=0)  # for an app that type_text had to start


class BrowserSettings(_Section):
    # auto: your Windows default browser when it is Brave, Chrome, or Edge, else Edge (ADR-049).
    # brave, chrome, msedge: that browser. chromium: Playwright's own build, after
    # `uv run playwright install chromium`. executable: a full path, which wins over channel.
    channel: Literal["auto", "brave", "msedge", "chromium", "chrome"] = "auto"
    executable: str = ""
    read_max_chars: int = Field(default=6000, ge=500)  # page text the model gets to see
    max_elements: int = Field(default=60, ge=10, le=300)  # links, buttons, and fields listed
    navigation_timeout_s: float = Field(default=30, gt=0)


class ContactsSettings(_Section):
    # Numbers saved without a country code get this one, for example "91" for India.
    default_country_code: str = Field(default="", pattern=r"^\d{0,3}$")
    match_threshold: float = Field(default=85, ge=0, le=100)


class WhatsAppSettings(_Section):
    # auto: WhatsApp Web in Jarvis's own browser profile, or the desktop app if Web is not
    # linked or will not load. Nothing falls back once Enter may have been pressed.
    method: Literal["auto", "web", "desktop"] = "auto"
    max_chars: int = Field(default=1000, ge=10, le=4000)
    verify_timeout_s: float = Field(default=15, gt=0)  # wait for the sent and delivered ticks


class NotificationsSettings(_Section):
    enabled: bool = True
    # Apps whose notifications Jarvis may read, by display name or app id. Everything else is
    # never read past its app name, and never stored.
    apps: list[str] = ["WhatsApp"]
    poll_s: float = Field(default=2, ge=0.5)  # how often the notification center is checked
    keep_days: float = Field(default=7, gt=0)  # older notification text is deleted
    max_read: int = Field(default=5, ge=1, le=20)  # notifications read out at once


class ServerSettings(_Section):
    port: int = Field(default=8765, ge=1024, le=65535)  # always on 127.0.0.1, never the network
    open_browser: bool = True
    speak_replies: bool = False  # also say the answers to commands typed on the page


class BridgeSettings(_Section):
    """Claude Code asks you through Jarvis: questions, permissions, notices (ADR-051)."""

    enabled: bool = True
    answer_timeout_s: float = Field(default=120, gt=0)  # then Claude Code asks as usual
    questions: bool = True  # answer AskUserQuestion by voice or the page
    permissions: bool = True  # allow or deny tool permissions by a clear spoken yes or no
    announce: bool = True  # say "Claude is waiting for you" and "Claude finished"
    # Reach your phone when nobody answers at the PC (ADR-052): "" (off), "ntfy", or "twilio".
    phone: Literal["", "ntfy", "twilio"] = ""
    escalate_after_s: float = Field(default=45, gt=0)


class PhoneSettings(_Section):
    """Your phone, for calls through Phone Link and for the bridge's phone escalation."""

    number: str = ""  # your own number, e.g. "+919876543210" (local.toml only)
    ntfy_server: str = "https://ntfy.sh"  # or your own ntfy server
    ntfy_topic: str = ""  # a long random topic name; anyone who knows it can read it
    twilio_from: str = ""  # a Twilio number that may call yours
    twilio_flow_sid: str = ""  # the Studio flow from docs/twilio-ask-flow.json


class TTSSettings(_Section):
    engine: Literal["piper", "sapi"] = "piper"
    piper_voice: str = "en_GB-alan-medium"
    piper_speed: float = Field(default=1.0, gt=0.25, le=3.0)
    rate: int = Field(default=0, ge=-10, le=10)  # SAPI only


class VoiceSettings(_Section):
    input_device: str | int | None = None  # None means the Windows default microphone
    ptt_hotkey: str = "ctrl+alt+j"
    stop_hotkey: str = "ctrl+alt+x"
    stt_model: str = "small.en"
    stt_device: Literal["cpu", "cuda", "auto"] = "auto"  # auto: the GPU with the gpu extra
    stt_compute_type: str = "int8"
    stt_cpu_threads: int = Field(default=8, ge=0)  # 0 lets CTranslate2 decide
    stt_beam_size: int = Field(default=1, ge=1, le=10)
    stt_language: str | None = "en"
    stt_hint: str = (
        "Jarvis, open, close, search, VS Code, Docker, WhatsApp, Notepad, Chrome, Calculator."
    )
    wake_word: str = "hey_jarvis"
    wake_word_enabled: bool = False
    wake_threshold: float = Field(default=0.5, gt=0, lt=1)
    vad_threshold: float = Field(default=0.5, gt=0, lt=1)
    end_silence_ms: int = Field(default=800, ge=200)
    max_utterance_s: float = Field(default=12, gt=1)
    no_speech_timeout_s: float = Field(default=5, gt=0.5)
    earcons: bool = True


class McpServerSettings(_Section):
    """One MCP server: a command over stdio or a URL over Streamable HTTP (ADR-059).

    Secrets are written as $NAME and come from .env; a server whose secrets are not set is
    skipped. Only the tools listed in `tools` reach the model ("*" means every tool).
    """

    enabled: bool = True
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    trusted: bool = False  # tools the server marks read-only may run without asking
    keywords: list[str] = Field(default_factory=list)  # words that offer this server's tools
    risk: dict[str, Risk] = Field(default_factory=dict)  # per tool; can only raise the risk
    # per tool: the parameters the model sees (required ones always); unlisted tools show all
    params: dict[str, list[str]] = Field(default_factory=dict)
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    label: str = ""  # how Jarvis names the server aloud, e.g. "GitHub"

    @model_validator(mode="after")
    def _one_transport(self) -> McpServerSettings:
        if bool(self.command) == bool(self.url):
            raise ValueError("an MCP server needs exactly one of command or url")
        return self


class McpSettings(_Section):
    enabled: bool = True
    connect_timeout_s: float = Field(default=60, gt=0)  # Docker may need to start the image
    call_timeout_s: float = Field(default=30, gt=0)
    servers: dict[str, McpServerSettings] = Field(default_factory=dict)


class MailSettings(_Section):
    """Your mailbox over IMAP and SMTP with an app password in .env (ADR-057)."""

    address: str = ""  # your email address (local.toml)
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    folder: str = "INBOX"
    max_list: int = Field(default=5, ge=1, le=20)  # emails listed at once
    body_chars: int = Field(default=4000, ge=500)  # of one email's text the model sees
    max_reply_chars: int = Field(default=5000, ge=50)
    signature: str = ""  # added under every reply
    timeout_s: float = Field(default=20, gt=0)


class CalendarSettings(_Section):
    """Your calendar's secret iCal address goes in .env as CALENDAR_ICS_URL (ADR-057)."""

    cache_s: float = Field(default=300, ge=0)  # download the calendar at most this often
    max_events: int = Field(default=10, ge=1)
    timeout_s: float = Field(default=20, gt=0)


class DictationSettings(_Section):
    """Hold a hotkey, speak, and the text is inserted at the cursor (ADR-054)."""

    enabled: bool = True
    hotkey: str = "ctrl+alt+d"
    paste_over_chars: int = Field(default=200, ge=0)  # longer text is pasted; 0 always pastes
    spoken_commands: bool = True  # "new line", "comma", "full stop", "question mark"
    remove_fillers: bool = True  # "um", "uh"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Jarvis"


class Settings(_Section):
    agent: AgentSettings = AgentSettings()
    llm: LLMSettings
    router: RouterSettings = RouterSettings()
    safety: SafetySettings = SafetySettings()
    apps: AppsSettings = AppsSettings()
    files: FilesSettings = FilesSettings()
    search: SearchSettings = SearchSettings()
    web: WebSettings = WebSettings()
    market: MarketSettings = MarketSettings()
    weather: WeatherSettings = WeatherSettings()
    system: SystemSettings = SystemSettings()
    ui: UISettings = UISettings()
    browser: BrowserSettings = BrowserSettings()
    contacts: ContactsSettings = ContactsSettings()
    whatsapp: WhatsAppSettings = WhatsAppSettings()
    notifications: NotificationsSettings = NotificationsSettings()
    mail: MailSettings = MailSettings()
    calendar: CalendarSettings = CalendarSettings()
    mcp: McpSettings = McpSettings()
    server: ServerSettings = ServerSettings()
    bridge: BridgeSettings = BridgeSettings()
    phone: PhoneSettings = PhoneSettings()
    tts: TTSSettings = TTSSettings()
    voice: VoiceSettings = VoiceSettings()
    dictation: DictationSettings = DictationSettings()
    data_dir: Path = Field(default_factory=default_data_dir)

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def whatsapp_profile_dir(self) -> Path:
        """WhatsApp Web's login lives apart from the browser the model drives (ADR-039)."""
        return self.data_dir / "whatsapp-profile"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into base: nested tables merge, everything else replaces."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigError(f"Config file not found: {path}")
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def load_settings(
    config_dir: Path | None = None,
    *,
    include_local: bool = True,
    env_file: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load and validate settings. Raises ConfigError with a readable message."""
    config_dir = config_dir or Path(os.environ.get("JARVIS_CONFIG_DIR", REPO_ROOT / "config"))
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)

    data = _read_toml(config_dir / "jarvis.toml", required=True)
    if include_local:
        data = deep_merge(data, _read_toml(config_dir / "local.toml", required=False))
    if overrides:
        data = deep_merge(data, overrides)

    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc
