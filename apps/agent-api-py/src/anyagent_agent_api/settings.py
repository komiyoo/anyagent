from __future__ import annotations

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8787, alias="PORT")

    agent_api_key: str = Field(alias="AGENT_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_base_url: AnyHttpUrl = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    enable_keyed_serialization: bool = Field(default=True, alias="ENABLE_KEYED_SERIALIZATION")

