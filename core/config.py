"""
Single source of truth for configuration.

Every module imports `get_config()` instead of reading config.yaml
directly, so the file is parsed exactly once per process and the
schema is validated in one place.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class WakeWordConfig(BaseModel):
    phrase: str = "start"
    model: str = "alexa"
    threshold: float = 0.5
    sample_rate: int = 16000
    frame_ms: int = 80


class AudioConfig(BaseModel):
    input_device: Optional[int] = None
    sample_rate: int = 16000
    channels: int = 1
    vad_aggressiveness: int = 2
    max_utterance_seconds: int = 20
    silence_timeout_ms: int = 900


class SttConfig(BaseModel):
    provider: str = "faster_whisper"
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: Optional[str] = None


class LlmConfig(BaseModel):
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "qwen3:30b-a3b"
    fast_model: str = "qwen2.5:3b"
    temperature: float = 0.2
    max_tokens: int = 1024
    request_timeout_s: int = 120


class VisionConfig(BaseModel):
    enabled: bool = True
    provider: str = "ollama"
    model: str = "gemma3:27b"


class TtsConfig(BaseModel):
    engine: str = "pyttsx3"
    piper_model_path: Optional[str] = None
    rate: int = 180
    voice: Optional[str] = None


class GesturesConfig(BaseModel):
    enabled: bool = False
    camera_index: int = 0


class SecurityConfig(BaseModel):
    require_confirmation: bool = True
    auto_approve_low_risk: bool = True
    confirmation_timeout_s: int = 30


class MemoryConfig(BaseModel):
    db_path: str = "data/agent_memory.sqlite3"


class DashboardConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/agent.log"
    max_bytes: int = 5_000_000
    backup_count: int = 3


class PathsConfig(BaseModel):
    workspace_dir: str = "~/PCAgentWorkspace"


class AppConfig(BaseModel):
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    gestures: GesturesConfig = Field(default_factory=GesturesConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    def resolved_workspace_dir(self) -> Path:
        p = Path(os.path.expanduser(self.paths.workspace_dir))
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolved_db_path(self) -> Path:
        p = PROJECT_ROOT / self.memory.db_path
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def resolved_log_path(self) -> Path:
        p = PROJECT_ROOT / self.logging.file
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


@functools.lru_cache(maxsize=1)
def _load_config(path: str) -> AppConfig:
    """Internal cached loader, keyed by a normalized string path so
    get_config() and get_config(None) always hit the SAME cache entry —
    passing an explicit None vs. relying on the default argument are
    different lru_cache keys otherwise, which silently created two
    independent config objects (one of which nothing else ever read)."""
    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return AppConfig(**raw)


def get_config(path: Optional[str] = None) -> AppConfig:
    """Load and cache config.yaml. Cached, so this is cheap to call anywhere."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {cfg_path}. Copy config.yaml.example if needed."
        )
    return _load_config(str(cfg_path))


def reload_config(path: Optional[str] = None) -> AppConfig:
    """Bypass the cache — used by tests and by the dashboard's settings page."""
    _load_config.cache_clear()
    return get_config(path)
