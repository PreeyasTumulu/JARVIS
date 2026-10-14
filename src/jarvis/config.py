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


class ProviderSettings(_Section):
    base_url: str
    model: str
    api_key_env: str = ""
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_s: float = Field(default=120, gt=0)

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


class AppsSettings(_Section):
    match_threshold: float = Field(default=75, ge=0, le=100)
    aliases: dict[str, str] = {}


class SearchSettings(_Section):
    max_results: int = Field(default=5, ge=1, le=10)
    region: str = "us-en"


class TTSSettings(_Section):
    engine: Literal["sapi"] = "sapi"
    rate: int = Field(default=0, ge=-10, le=10)


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Jarvis"


class Settings(_Section):
    agent: AgentSettings = AgentSettings()
    llm: LLMSettings
    safety: SafetySettings = SafetySettings()
    apps: AppsSettings = AppsSettings()
    search: SearchSettings = SearchSettings()
    tts: TTSSettings = TTSSettings()
    data_dir: Path = Field(default_factory=default_data_dir)


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
