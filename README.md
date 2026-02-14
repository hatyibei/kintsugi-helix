# Kintsugi-Helix

> **金継ぎ (Kintsugi)** - The Japanese art of repairing broken pottery with gold, treating breakage as part of the object's history.

An autonomous maintenance engineer powered by Vertex AI (Gemini 2.5 Pro) that detects, analyzes, and repairs software defects in Java/Spring Boot applications.

## Overview

Kintsugi-Helix is an AI-driven system that implements the "Self-Healing Software" paradigm through four core capabilities:

| Phase | Japanese | Description |
|-------|----------|-------------|
| **Sensing** | 感知 (Kanchi) | Detects errors from Cloud Logging and performs root cause analysis |
| **Reflection** | 反射 (Hansha) | Generates failing JUnit tests using Testcontainers to confirm bugs |
| **Evolution** | 進化 (Shinka) | Applies fixes and structural improvements via OpenRewrite recipes |
| **Governance** | 統治 (Tōchi) | Analyzes blast radius to determine auto-merge vs PR creation |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Kintsugi-Helix                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Sensing    │───▶│  Reflection  │───▶│  Evolution   │      │
│  │  (感知)      │    │   (反射)     │    │   (進化)     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────────────────────────────────────────────┐      │
│  │                    Governance (統治)                  │      │
│  │         Blast Radius Analysis & Auto-Merge            │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                     External Services                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │  Cloud     │ │  Vertex AI │ │  Cloud Run │ │  GitHub    │   │
│  │  Logging   │ │  Gemini    │ │            │ │  API       │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
kintsugi-helix/
├── agent-core/                  # Python agent implementation
│   ├── src/
│   │   ├── sensing/            # Error detection & RCA
│   │   ├── reflection/         # Test generation
│   │   ├── evolution/          # Code repair & refactoring
│   │   ├── governance/         # Blast radius & PR management
│   │   ├── mcp/               # Model Context Protocol server
│   │   └── utils/             # Shared utilities
│   ├── tests/                  # Agent test suite
│   └── config/                 # Configuration files
│
├── target-app/                  # Sample Spring Boot app (with bugs)
│   ├── src/main/java/          # Application source
│   ├── src/test/java/          # Test suite
│   └── pom.xml                 # Maven configuration
│
├── infrastructure/              # Cloud infrastructure
│   ├── terraform/              # Terraform modules
│   │   ├── modules/
│   │   │   ├── cloud-run/
│   │   │   ├── logging/
│   │   │   └── vertex-ai/
│   │   └── environments/
│   │       ├── dev/
│   │       └── prod/
│   └── scripts/                # Deployment scripts
│
├── docs/                        # Documentation
├── .github/workflows/           # CI/CD pipelines
├── CLAUDE.md                    # AI assistant guidelines
└── README.md                    # This file
```

## Tech Stack

| Category | Technology |
|----------|------------|
| **Agent Core** | Python 3.11+, Vertex AI SDK |
| **Target App** | Java 21, Spring Boot 3.2 |
| **AI Model** | Gemini 2.5 Pro / Flash |
| **Testing** | Testcontainers, JUnit 5 |
| **Refactoring** | OpenRewrite |
| **Infrastructure** | Cloud Run, Cloud Logging, Terraform |
| **Protocol** | MCP (Model Context Protocol) |

## Quick Start

### Prerequisites

- Python 3.11+
- Java 21+
- Docker
- Google Cloud SDK
- Terraform 1.5+

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/kintsugi-helix.git
cd kintsugi-helix

# Set up Python environment
cd agent-core
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up Google Cloud credentials
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id

# Build target application
cd ../target-app
./mvnw clean package
```

### Running the Agent

```bash
# Start the agent in development mode
cd agent-core
python -m src.main --mode=dev

# Run with specific incident ID
python -m src.main --incident-id=abc123
```

### Infrastructure Deployment

```bash
cd infrastructure/terraform/environments/dev
terraform init
terraform plan
terraform apply
```

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_CLOUD_PROJECT` | GCP Project ID | Required |
| `VERTEX_AI_LOCATION` | Vertex AI region | `us-central1` |
| `LOG_FILTER` | Cloud Logging filter | `severity>=ERROR` |
| `AUTO_MERGE_THRESHOLD` | Blast radius threshold | `0.3` |
| `GITHUB_TOKEN` | GitHub API token | Required for PRs |

## Development

### Running Tests

```bash
# Agent tests
cd agent-core
pytest tests/ -v

# Target app tests
cd target-app
./mvnw test
```

### Code Style

```bash
# Python
ruff check agent-core/
black agent-core/

# Java
./mvnw spotless:apply
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- Google Cloud Platform for Vertex AI and Cloud services
- The OpenRewrite project for code transformation capabilities
- Testcontainers for enabling realistic test environments

---

**Built for Google Cloud Hackathon 2025**
