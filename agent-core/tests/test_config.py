"""Tests for configuration management."""

import os
import pytest
from unittest.mock import patch

from src.utils.config import Settings


def test_settings_defaults():
    """Test default settings values."""
    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}):
        settings = Settings()

        assert settings.google_cloud_project == "test-project"
        assert settings.vertex_ai_location == "us-central1"
        assert settings.log_filter == "severity>=ERROR"
        assert settings.auto_merge_threshold == 0.3
        assert settings.dry_run is False
        assert settings.mode == "dev"


def test_settings_override():
    """Test settings can be overridden via env vars."""
    env_vars = {
        "GOOGLE_CLOUD_PROJECT": "override-project",
        "VERTEX_AI_LOCATION": "europe-west1",
        "LOG_FILTER": "severity>=WARNING",
        "AUTO_MERGE_THRESHOLD": "0.5",
        "DRY_RUN": "true",
        "MODE": "prod",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        settings = Settings()

        assert settings.google_cloud_project == "override-project"
        assert settings.vertex_ai_location == "europe-west1"
        assert settings.log_filter == "severity>=WARNING"
        assert settings.auto_merge_threshold == 0.5
        assert settings.dry_run is True
        assert settings.mode == "prod"


def test_settings_validation():
    """Test settings validation."""
    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test"}):
        # Valid threshold
        settings = Settings(auto_merge_threshold=0.5)
        assert settings.auto_merge_threshold == 0.5


def test_settings_invalid_threshold():
    """Test that invalid threshold raises error."""
    with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test"}):
        with pytest.raises(ValueError):
            Settings(auto_merge_threshold=1.5)  # > 1.0


def test_settings_missing_required():
    """Test that missing required field raises error."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError):
            Settings()  # Missing GOOGLE_CLOUD_PROJECT
