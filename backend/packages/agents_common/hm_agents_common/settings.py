from __future__ import annotations

from functools import lru_cache
from typing import Literal

from hm_core.config import HMSettings


class AgentSettings(HMSettings):
    session_backend: Literal["file", "s3"] = "file"
    session_dir: str = ".sessions"
    session_bucket: str = ""

    otel_service_name: str = ""
    otel_exporter_otlp_endpoint: str = ""
    otel_console_exporter: bool = False

    # Sliding window of messages kept in context (32k context goes fast with tool results).
    agent_window_size: int = 20


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
