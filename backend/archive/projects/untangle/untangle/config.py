from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from hm_core.config import HMSettings, find_env_file


class Settings(HMSettings):
    """Project settings. Env vars are prefixed, e.g. UNTANGLE_PORT=9000."""

    model_config = SettingsConfigDict(env_prefix="UNTANGLE_", env_file=find_env_file(), extra="ignore")

    port: int = 8104
    inference_port: int = 8204
    # Containers/k8s set the generic INFERENCE_URL; local dev uses the default.
    inference_url: str = Field(
        "http://localhost:8204",
        validation_alias=AliasChoices("UNTANGLE_INFERENCE_URL", "INFERENCE_URL"),
    )
    model_name: str = "untangle-baseline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
