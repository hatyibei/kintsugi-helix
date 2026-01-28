# CLAUDE.md - AI Assistant Guidelines for Kintsugi-Helix

This document provides comprehensive guidance for AI assistants working with the Kintsugi-Helix codebase.

## Project Overview

**Kintsugi-Helix** is an autonomous maintenance engineer system that uses Vertex AI (Gemini 1.5 Pro) to automatically detect, analyze, and repair bugs in Java/Spring Boot applications. The project is built for the Google Cloud Hackathon.

### Core Philosophy

The system follows the Japanese art of **Kintsugi** (金継ぎ) - treating software defects not as flaws to hide, but as opportunities for improvement and evolution.

### Four Pillars

1. **Sensing (感知)** - Error detection via Cloud Logging + AI root cause analysis
2. **Reflection (反射)** - Automated failing test generation with Testcontainers
3. **Evolution (進化)** - Code fixes and structural refactoring via OpenRewrite
4. **Governance (統治)** - Blast radius analysis for safe automated deployment

---

## Repository Structure

```
kintsugi-helix/
├── agent-core/                  # Python - Main AI agent
│   ├── src/
│   │   ├── sensing/            # Cloud Logging integration, error parsing
│   │   │   ├── __init__.py
│   │   │   ├── log_collector.py     # Fetches logs from Cloud Logging
│   │   │   └── root_cause_analyzer.py # Gemini-powered RCA
│   │   │
│   │   ├── reflection/         # Test generation module
│   │   │   ├── __init__.py
│   │   │   ├── test_generator.py    # Generates JUnit tests
│   │   │   └── testcontainer_runner.py # Runs tests in containers
│   │   │
│   │   ├── evolution/          # Code modification module
│   │   │   ├── __init__.py
│   │   │   ├── code_fixer.py        # Applies targeted fixes
│   │   │   └── openrewrite_executor.py # Runs OpenRewrite recipes
│   │   │
│   │   ├── governance/         # Decision & PR management
│   │   │   ├── __init__.py
│   │   │   ├── blast_radius.py      # Impact analysis
│   │   │   └── pr_manager.py        # GitHub PR creation/merge
│   │   │
│   │   ├── mcp/               # Model Context Protocol server
│   │   │   ├── __init__.py
│   │   │   └── server.py           # MCP server implementation
│   │   │
│   │   ├── utils/             # Shared utilities
│   │   │   ├── __init__.py
│   │   │   ├── vertex_client.py    # Vertex AI SDK wrapper
│   │   │   ├── git_utils.py        # Git operations helper
│   │   │   └── config.py           # Configuration management
│   │   │
│   │   └── main.py            # Entry point
│   │
│   ├── tests/                  # Pytest test suite
│   ├── config/                 # YAML configuration files
│   ├── requirements.txt        # Python dependencies
│   └── Dockerfile             # Agent container image
│
├── target-app/                  # Java - Sample vulnerable app
│   ├── src/main/java/com/kintsugi/demo/
│   │   ├── controller/         # REST controllers
│   │   ├── service/            # Business logic
│   │   ├── repository/         # Data access
│   │   ├── model/              # Domain entities
│   │   └── config/             # Spring configuration
│   ├── src/test/java/          # JUnit tests
│   ├── pom.xml                 # Maven build file
│   └── Dockerfile             # App container image
│
├── infrastructure/              # Cloud infrastructure
│   ├── terraform/
│   │   ├── modules/            # Reusable Terraform modules
│   │   │   ├── cloud-run/      # Cloud Run service
│   │   │   ├── logging/        # Log sinks and filters
│   │   │   └── vertex-ai/      # Vertex AI endpoints
│   │   └── environments/       # Environment-specific configs
│   │       ├── dev/
│   │       └── prod/
│   └── scripts/                # Shell scripts for deployment
│
├── docs/                        # Additional documentation
├── .github/workflows/           # GitHub Actions CI/CD
├── CLAUDE.md                    # This file
└── README.md                    # Project overview
```

---

## Technology Stack & Conventions

### Python (agent-core)

**Version:** Python 3.11+

**Key Dependencies:**
- `google-cloud-aiplatform` - Vertex AI SDK
- `google-cloud-logging` - Cloud Logging client
- `pydantic` - Data validation
- `httpx` - Async HTTP client
- `pytest` - Testing framework

**Code Style:**
- Use `ruff` for linting (configured in `pyproject.toml`)
- Use `black` for formatting
- Type hints required for all function signatures
- Docstrings in Google style

**Import Order:**
```python
# 1. Standard library
import os
import json

# 2. Third-party packages
from google.cloud import aiplatform
from pydantic import BaseModel

# 3. Local imports
from src.utils.config import Settings
```

**Naming Conventions:**
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

### Java (target-app)

**Version:** Java 21

**Framework:** Spring Boot 3.2

**Key Dependencies:**
- Spring Web
- Spring Data JPA
- H2 Database (test)
- Testcontainers
- OpenRewrite

**Code Style:**
- Google Java Style Guide
- Use `spotless-maven-plugin` for formatting

**Package Structure:**
```
com.kintsugi.demo
├── controller      # @RestController classes
├── service         # @Service classes
├── repository      # @Repository interfaces
├── model           # Entity classes
├── dto             # Data transfer objects
├── config          # @Configuration classes
└── exception       # Custom exceptions
```

### Terraform

**Version:** 1.5+

**Conventions:**
- One resource type per file where practical
- Use modules for reusable infrastructure
- Variables in `variables.tf`, outputs in `outputs.tf`
- Environment-specific values in `terraform.tfvars`

---

## Development Workflows

### Local Development

```bash
# Agent development
cd agent-core
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Includes dev tools

# Run agent locally
python -m src.main --mode=dev

# Run tests
pytest tests/ -v --cov=src

# Target app development
cd target-app
./mvnw spring-boot:run

# Run Java tests
./mvnw test
```

### Testing Strategy

**Agent Tests:**
- Unit tests in `agent-core/tests/unit/`
- Integration tests in `agent-core/tests/integration/`
- Use `pytest-asyncio` for async tests
- Mock external services (Vertex AI, Cloud Logging) in unit tests

**Target App Tests:**
- Unit tests with JUnit 5
- Integration tests with Testcontainers
- Use `@SpringBootTest` sparingly

### Git Workflow

**Branch Naming:**
- `feature/<description>` - New features
- `fix/<description>` - Bug fixes
- `refactor/<description>` - Code improvements
- `docs/<description>` - Documentation updates

**Commit Message Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Example:**
```
feat(sensing): add Cloud Logging error extraction

Implements LogCollector class that queries Cloud Logging API
for ERROR severity logs within a configurable time window.

Closes #123
```

---

## Key Implementation Details

### Vertex AI Integration

```python
# Location: agent-core/src/utils/vertex_client.py

# Always use the async client for better performance
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel

# Model selection
GEMINI_PRO = "gemini-1.5-pro"     # Complex reasoning tasks
GEMINI_FLASH = "gemini-1.5-flash" # Fast, simple tasks

# Initialize in main.py
aiplatform.init(
    project=settings.google_cloud_project,
    location=settings.vertex_ai_location
)
```

### Error Handling

```python
# Custom exceptions in agent-core/src/utils/exceptions.py
class KintsugiError(Exception):
    """Base exception for Kintsugi-Helix."""
    pass

class LogCollectionError(KintsugiError):
    """Failed to collect logs from Cloud Logging."""
    pass

class TestGenerationError(KintsugiError):
    """Failed to generate test case."""
    pass
```

### Configuration Management

```python
# Use Pydantic Settings for configuration
# Location: agent-core/src/utils/config.py

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    google_cloud_project: str
    vertex_ai_location: str = "us-central1"
    log_filter: str = "severity>=ERROR"
    auto_merge_threshold: float = 0.3

    class Config:
        env_file = ".env"
```

### Blast Radius Calculation

The governance module calculates blast radius based on:
1. Number of files affected
2. Cyclomatic complexity changes
3. Test coverage of affected areas
4. Dependencies affected

```python
# Threshold values
LOW_RISK = 0.3      # Auto-merge allowed
MEDIUM_RISK = 0.6   # PR with fast-track review
HIGH_RISK = 1.0     # PR with full review required
```

---

## Common Tasks for AI Assistants

### Adding a New Sensing Source

1. Create new collector in `agent-core/src/sensing/`
2. Implement the `BaseCollector` interface
3. Register in `agent-core/src/sensing/__init__.py`
4. Add configuration options to `Settings`
5. Write unit tests

### Adding a New OpenRewrite Recipe

1. Add recipe to `target-app/rewrite.yml`
2. Document recipe purpose in comments
3. Test with `./mvnw rewrite:dryRun`
4. Add integration test

### Modifying Blast Radius Logic

1. Update `agent-core/src/governance/blast_radius.py`
2. Adjust threshold constants if needed
3. Update tests in `agent-core/tests/unit/test_blast_radius.py`
4. Document changes in this file

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | - | GCP project ID |
| `VERTEX_AI_LOCATION` | No | `us-central1` | Vertex AI region |
| `LOG_FILTER` | No | `severity>=ERROR` | Cloud Logging filter |
| `AUTO_MERGE_THRESHOLD` | No | `0.3` | Blast radius threshold |
| `GITHUB_TOKEN` | Yes* | - | For PR creation (*if using governance) |
| `TARGET_REPO` | No | - | Target repository for fixes |
| `DRY_RUN` | No | `false` | Skip actual modifications |

---

## Troubleshooting

### Common Issues

**"Permission denied" for Cloud Logging:**
```bash
gcloud auth application-default login
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="user:$EMAIL" \
    --role="roles/logging.viewer"
```

**Vertex AI quota exceeded:**
- Check quotas in Cloud Console
- Implement exponential backoff
- Consider using Gemini Flash for simpler tasks

**Testcontainers not starting:**
- Ensure Docker daemon is running
- Check Docker socket permissions
- Verify sufficient disk space

---

## Important Reminders for AI Assistants

1. **Always verify GCP authentication** before running agent commands
2. **Never commit credentials** - use environment variables or Secret Manager
3. **Test locally first** before deploying to Cloud Run
4. **Check blast radius** before auto-merging any changes
5. **Document significant changes** in commit messages and this file
6. **Prefer Gemini Flash** for simple tasks to reduce costs
7. **Use structured outputs** when prompting Gemini for code generation
8. **Validate generated tests** run successfully before committing
9. **Follow the four pillars** - Sensing → Reflection → Evolution → Governance

---

## Quick Reference Commands

```bash
# Agent development
cd agent-core && python -m src.main --help
pytest tests/ -v
ruff check . && black .

# Target app
cd target-app && ./mvnw spring-boot:run
./mvnw test
./mvnw rewrite:run  # Apply OpenRewrite recipes

# Infrastructure
cd infrastructure/terraform/environments/dev
terraform init && terraform plan

# Docker
docker build -t kintsugi-agent ./agent-core
docker build -t kintsugi-target ./target-app

# GCP
gcloud run deploy kintsugi-agent --source ./agent-core
gcloud logging read "severity>=ERROR" --limit=10
```

---

*Last updated: January 2025*
