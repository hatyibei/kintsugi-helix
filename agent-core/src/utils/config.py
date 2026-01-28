"""Configuration management for Kintsugi-Helix.

Uses Pydantic Settings for environment variable loading and validation.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Google Cloud
    google_cloud_project: str = Field(
        ...,
        description="Google Cloud Project ID",
    )
    vertex_ai_location: str = Field(
        default="us-central1",
        description="Vertex AI region",
    )

    # Logging
    log_filter: str = Field(
        default="severity>=ERROR",
        description="Cloud Logging filter expression",
    )
    log_lookback_hours: int = Field(
        default=24,
        description="Hours to look back for logs",
    )

    # Governance
    auto_merge_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Blast radius threshold for auto-merge (0.0-1.0)",
    )
    dry_run: bool = Field(
        default=False,
        description="Skip actual modifications when True",
    )

    # GitHub
    github_token: str | None = Field(
        default=None,
        description="GitHub API token for PR creation",
    )
    target_repo: str | None = Field(
        default=None,
        description="Target repository for fixes (owner/repo)",
    )

    # Model Selection
    default_model: Literal["gemini-1.5-pro", "gemini-1.5-flash"] = Field(
        default="gemini-1.5-pro",
        description="Default Gemini model to use",
    )

    # Agent Mode
    mode: Literal["dev", "prod", "test"] = Field(
        default="dev",
        description="Agent running mode",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: The application settings.
    """
    return Settings()
