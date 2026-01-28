"""Vertex AI client wrapper for Kintsugi-Helix.

Provides a unified interface for interacting with Gemini models.
"""

import json
from typing import Any

import structlog
from google.cloud import aiplatform
from tenacity import retry, stop_after_attempt, wait_exponential
from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

from src.utils.config import Settings

logger = structlog.get_logger()


class VertexAIClient:
    """Client for interacting with Vertex AI Gemini models."""

    GEMINI_PRO = "gemini-1.5-pro"
    GEMINI_FLASH = "gemini-1.5-flash"

    def __init__(self, settings: Settings) -> None:
        """Initialize the Vertex AI client.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the Vertex AI platform."""
        if not self._initialized:
            aiplatform.init(
                project=self.settings.google_cloud_project,
                location=self.settings.vertex_ai_location,
            )
            self._initialized = True
            logger.info(
                "Vertex AI initialized",
                project=self.settings.google_cloud_project,
                location=self.settings.vertex_ai_location,
            )

    def _get_model(self, model_name: str | None = None) -> GenerativeModel:
        """Get a Gemini model instance.

        Args:
            model_name: Optional model name. Uses default if not specified.

        Returns:
            GenerativeModel: The model instance.
        """
        self.initialize()
        name = model_name or self.settings.default_model
        return GenerativeModel(name)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate_text(
        self,
        prompt: str,
        model_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        """Generate text using Gemini.

        Args:
            prompt: The input prompt.
            model_name: Optional model name override.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum output tokens.

        Returns:
            str: The generated text response.
        """
        model = self._get_model(model_name)
        config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        logger.debug("Generating text", model=model_name, prompt_length=len(prompt))

        response = await model.generate_content_async(
            prompt,
            generation_config=config,
        )

        return response.text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        model_name: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate structured JSON output using Gemini.

        Args:
            prompt: The input prompt.
            response_schema: JSON schema for the expected response.
            model_name: Optional model name override.
            temperature: Sampling temperature (0.0-1.0).

        Returns:
            dict: The parsed JSON response.
        """
        model = self._get_model(model_name)

        schema_str = json.dumps(response_schema, indent=2)
        enhanced_prompt = f"""{prompt}

Respond with valid JSON matching this schema:
```json
{schema_str}
```

Output only the JSON, no additional text."""

        config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=8192,
        )

        logger.debug(
            "Generating structured output",
            model=model_name,
            schema_keys=list(response_schema.get("properties", {}).keys()),
        )

        response = await model.generate_content_async(
            enhanced_prompt,
            generation_config=config,
        )

        # Extract JSON from response
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        return json.loads(text.strip())

    async def analyze_code(
        self,
        code: str,
        context: str,
        task: str,
    ) -> str:
        """Analyze code with given context and task.

        Args:
            code: The source code to analyze.
            context: Additional context (error logs, stack traces, etc.).
            task: The analysis task to perform.

        Returns:
            str: Analysis results.
        """
        prompt = f"""You are an expert software engineer analyzing code.

## Task
{task}

## Context
{context}

## Code
```
{code}
```

Provide a detailed analysis."""

        return await self.generate_text(prompt, temperature=0.3)

    async def generate_code(
        self,
        specification: str,
        language: str,
        context: str | None = None,
    ) -> str:
        """Generate code based on specification.

        Args:
            specification: What the code should do.
            language: Target programming language.
            context: Optional existing code context.

        Returns:
            str: Generated code.
        """
        context_section = f"\n## Existing Context\n```\n{context}\n```" if context else ""

        prompt = f"""You are an expert {language} developer.
Generate code that meets the following specification.

## Specification
{specification}
{context_section}

Output only the code, no explanations.
Ensure the code is complete, correct, and follows best practices."""

        return await self.generate_text(prompt, temperature=0.2)
