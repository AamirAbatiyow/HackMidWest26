from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from hm_core.config import HMSettings, find_env_file


class Settings(HMSettings):
    """Project settings. Env vars are prefixed, e.g. VOUCH_PORT=9000."""

    model_config = SettingsConfigDict(env_prefix="VOUCH_", env_file=find_env_file(), extra="ignore")

    port: int = 8101
    inference_port: int = 8201
    # Containers/k8s set the generic INFERENCE_URL; local dev uses the default.
    inference_url: str = Field(
        "http://localhost:8201",
        validation_alias=AliasChoices("VOUCH_INFERENCE_URL", "INFERENCE_URL"),
    )
    model_name: str = "vouch-risk"

    # auto: inference service if reachable, else in-process torch model, else heuristic fallback.
    scorer: Literal["auto", "http", "local", "heuristic"] = "auto"
    # auto: live LLM nodes when Akamai or Bedrock is configured, otherwise deterministic fallbacks.
    llm_mode: Literal["auto", "live", "offline"] = "auto"
    lime_samples: int = 400

    # Money limits, integer cents.
    approval_limit_cents: int = 500_000  # $5,000 clerk approval limit
    fast_pay_limit_cents: int = 250_000  # $2,500
    single_payment_limit_cents: int = 5_000_000  # $50,000
    batch_limit_cents: int = 10_000_000  # $100,000 per batch

    # Cash-forecast stub.
    opening_balance_cents: int = 18_500_000
    cash_buffer_cents: int = 2_500_000

    owner_name: str = "Dana Whitfield"
    business_name: str = "Heartland Provisions Co."


@lru_cache
def get_settings() -> Settings:
    return Settings()
