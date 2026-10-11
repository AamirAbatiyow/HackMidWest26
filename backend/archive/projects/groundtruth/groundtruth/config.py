from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from hm_core.config import HMSettings, find_env_file


class Settings(HMSettings):
    """Project settings. Env vars are prefixed, e.g. GROUNDTRUTH_PORT=9000."""

    model_config = SettingsConfigDict(env_prefix="GROUNDTRUTH_", env_file=find_env_file(), extra="ignore")

    port: int = 8102
    inference_port: int = 8202
    # Containers/k8s set the generic INFERENCE_URL; local dev uses the default.
    inference_url: str = Field(
        "http://localhost:8202",
        validation_alias=AliasChoices("GROUNDTRUTH_INFERENCE_URL", "INFERENCE_URL"),
    )
    model_name: str = "groundtruth-baseline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
