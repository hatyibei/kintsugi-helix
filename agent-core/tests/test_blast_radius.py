"""Tests for blast radius analyzer."""

import pytest

from src.evolution.code_fixer import CodeFix
from src.governance.blast_radius import (
    BlastRadiusAnalyzer,
    BlastRadiusResult,
    LOW_RISK,
    MEDIUM_RISK,
)
from src.utils.config import Settings


class MockSettings:
    """Mock settings for testing."""

    google_cloud_project = "test-project"
    vertex_ai_location = "us-central1"
    auto_merge_threshold = 0.3
    dry_run = True


class MockVertexClient:
    """Mock Vertex AI client for testing."""

    async def generate_structured(self, prompt, response_schema, temperature=0.2):
        """Return mock structured response."""
        return {
            "score": 0.2,
            "dependencies_affected": ["service-a", "service-b"],
            "test_coverage_estimate": 0.8,
            "reasoning": "Low impact change with good test coverage",
        }


@pytest.fixture
def analyzer():
    """Create analyzer instance for testing."""
    settings = MockSettings()
    vertex_client = MockVertexClient()
    return BlastRadiusAnalyzer(settings, vertex_client)


@pytest.fixture
def sample_fix():
    """Create sample code fix for testing."""
    return CodeFix(
        file_path="src/main/java/com/example/Service.java",
        original_code="public void method() { }",
        fixed_code="public void method() { /* fixed */ }",
        description="Fix null pointer exception",
        lines_changed=5,
        confidence=0.9,
    )


def test_simple_analysis_low_risk(analyzer, sample_fix):
    """Test simple analysis with low risk fix."""
    result = analyzer.analyze_simple([sample_fix])

    assert isinstance(result, BlastRadiusResult)
    assert result.files_affected == 1
    assert result.risk_level in ["low", "medium"]


def test_simple_analysis_multiple_fixes(analyzer, sample_fix):
    """Test simple analysis with multiple fixes."""
    fixes = [sample_fix] * 5
    result = analyzer.analyze_simple(fixes)

    assert result.files_affected == 5
    assert result.score > 0


def test_risk_level_calculation(analyzer):
    """Test risk level calculation from score."""
    assert analyzer._calculate_risk_level(0.1) == "low"
    assert analyzer._calculate_risk_level(LOW_RISK) == "low"
    assert analyzer._calculate_risk_level(0.5) == "medium"
    assert analyzer._calculate_risk_level(MEDIUM_RISK) == "medium"
    assert analyzer._calculate_risk_level(0.8) == "high"
    assert analyzer._calculate_risk_level(1.5) == "critical"


def test_recommendation_auto_merge(analyzer):
    """Test auto-merge recommendation."""
    recommendation = analyzer._get_recommendation(0.2, 0.8)
    assert recommendation == "auto_merge"


def test_recommendation_fast_review(analyzer):
    """Test fast review recommendation."""
    recommendation = analyzer._get_recommendation(0.5, 0.6)
    assert recommendation == "fast_review"


def test_recommendation_full_review(analyzer):
    """Test full review recommendation."""
    recommendation = analyzer._get_recommendation(0.8, 0.5)
    assert recommendation == "full_review"


def test_should_auto_merge_low_risk(analyzer):
    """Test auto-merge decision for low risk."""
    result = BlastRadiusResult(
        score=0.2,
        risk_level="low",
        files_affected=1,
        dependencies_affected=[],
        test_coverage_estimate=0.9,
        recommendation="auto_merge",
        reasoning="Low risk",
    )

    assert analyzer.should_auto_merge(result) is True


def test_should_not_auto_merge_high_risk(analyzer):
    """Test auto-merge rejection for high risk."""
    result = BlastRadiusResult(
        score=0.7,
        risk_level="high",
        files_affected=10,
        dependencies_affected=["a", "b", "c"],
        test_coverage_estimate=0.3,
        recommendation="full_review",
        reasoning="High risk",
    )

    assert analyzer.should_auto_merge(result) is False


@pytest.mark.asyncio
async def test_ai_analysis(analyzer, sample_fix):
    """Test AI-powered analysis."""
    result = await analyzer.analyze([sample_fix])

    assert isinstance(result, BlastRadiusResult)
    assert result.score == 0.2
    assert "service-a" in result.dependencies_affected
    assert result.test_coverage_estimate == 0.8
