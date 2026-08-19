"""Application settings loaded from environment variables without side effects."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for GuidelineOps-CN.

    Credentials are deliberately optional: offline imports and metadata-only
    workflows must be usable without an NCBI or Wanfang account. Adapters that
    need a credential can issue a clear runtime error at the point of use.
    """

    ncbi_email: str | None = None
    ncbi_tool: str = "guidelineops-cn"
    ncbi_api_key: str | None = None
    crossref_mailto: str | None = None
    wanfang_app_key: str | None = None
    wanfang_app_secret: str | None = None
    database_url: str = "sqlite:///./data/guidelineops.db"
    data_dir: Path = Path("data")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )
