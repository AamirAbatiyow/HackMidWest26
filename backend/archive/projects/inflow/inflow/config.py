from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from hm_core.config import HMSettings, find_env_file


class Settings(HMSettings):
    """Project settings. Env vars are prefixed, e.g. INFLOW_PORT=9000."""

    model_config = SettingsConfigDict(env_prefix="INFLOW_", env_file=find_env_file(), extra="ignore")

    port: int = 8103
    inference_port: int = 8203
    # Containers/k8s set the generic INFERENCE_URL; local dev uses the default.
    inference_url: str = Field(
        "http://localhost:8203",
        validation_alias=AliasChoices("INFLOW_INFERENCE_URL", "INFERENCE_URL"),
    )
    model_name: str = "inflow-baseline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
