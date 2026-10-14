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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.tools.base import Risk

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """The configuration is missing or invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSettings(_Section):
    max_iterations: int = Field(default=6, ge=1, le=20)
    turn_timeout_s: float = Field(default=120, gt=0)
    tool_timeout_s: float = Field(default=20, gt=0)
    max_tool_calls_per_step: int = Field(default=4, ge=1)
    history_turns: int = Field(default=8, ge=0)
    max_tool_result_chars: int = Field(default=4000, ge=200)
    tool_routing: Literal["keywords", "all"] = "keywords"


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


class SafetySettings(_Section):
    app_allowlist: list[str] = []
    unlisted_apps: Literal["confirm", "block"] = "confirm"
    confirm_timeout_s: float = Field(default=30, gt=0)
    tool_risk_overrides: dict[str, Risk] = {}
    safe_to_close: list[str] = []


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
    stt_device: Literal["cpu", "cuda", "auto"] = "cpu"
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


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Jarvis"


class Settings(_Section):
    agent: AgentSettings = AgentSettings()
    llm: LLMSettings
    safety: SafetySettings = SafetySettings()
    apps: AppsSettings = AppsSettings()
    files: FilesSettings = FilesSettings()
    search: SearchSettings = SearchSettings()
    tts: TTSSettings = TTSSettings()
    voice: VoiceSettings = VoiceSettings()
    data_dir: Path = Field(default_factory=default_data_dir)

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"


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
