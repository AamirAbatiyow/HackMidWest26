from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr

from hm_core.config import HMSettings
from hm_core.errors import ConfigError


class LLMSettings(HMSettings):
    llm_provider: Literal["akamai", "bedrock", "auto"] = "auto"

    akamai_inference_base_url: str = ""
    akamai_inference_api_key: SecretStr = SecretStr("")
    akamai_inference_model: str = ""

    # Akamai team-key limits: 60 req/min, 32k context, 4096 max output tokens.
    llm_requests_per_minute: int = 60
    llm_max_context_tokens: int = 32_000
    llm_max_output_tokens: int = 4_096
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 4

    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""

    @property
    def akamai_configured(self) -> bool:
        return bool(
            self.akamai_inference_base_url
            and self.akamai_inference_api_key.get_secret_value()
            and self.akamai_inference_model
        )

    @property
    def bedrock_configured(self) -> bool:
        return bool(self.bedrock_model_id)

    def resolve_provider(self) -> Literal["akamai", "bedrock"]:
        """Pick the primary provider. `auto` prefers Akamai, then Bedrock."""
        if self.llm_provider == "akamai" or (self.llm_provider == "auto" and self.akamai_configured):
            if not self.akamai_configured:
                raise ConfigError(
                    "Set AKAMAI_INFERENCE_BASE_URL, AKAMAI_INFERENCE_API_KEY, AKAMAI_INFERENCE_MODEL"
                )
            return "akamai"
        if self.bedrock_configured:
            return "bedrock"
        raise ConfigError("No LLM provider configured: set AKAMAI_INFERENCE_* or BEDROCK_MODEL_ID in .env")


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
