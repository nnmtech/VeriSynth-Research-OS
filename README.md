# VeriSynth Research OS

We present VeriSynth Research OS, the first production system to fully implement and extend the Massively Decomposed Agentic Processes (MDAP) framework introduced by Meyerson et al. (2025).

[![Deploy to Cloud Run](https://github.com/nnmtech/VeriSynth-Research-OS/actions/workflows/deploy.yml/badge.svg)](https://github.com/nnmtech/VeriSynth-Research-OS/actions/workflows/deploy.yml)

## 🚀 Quick Start

### Local Development

```bash
# Clone the repository
git clone https://github.com/nnmtech/VeriSynth-Research-OS.git
cd VeriSynth-Research-OS

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your configuration

# Run development server
make dev
```

Visit http://localhost:8080/docs for interactive API documentation.

### One-Click Cloud Run Deploy

[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run)

Or deploy manually:

```bash
# Set up Google Cloud
gcloud config set project YOUR_PROJECT_ID

# Create secrets in Secret Manager
echo -n "your-openai-key" | gcloud secrets create openai-api-key --data-file=-
echo -n "your-anthropic-key" | gcloud secrets create anthropic-api-key --data-file=-

# Deploy to Cloud Run
make deploy-with-secrets
```

## 📋 Features

### Core Components

- **MAKER (Massively Agentic Knowledge Evolution and Reasoning)**
  - `first_to_ahead_by_k` strategy for optimal agent selection
  - Dynamic red-flagging for quality control
  - Concurrent execution with configurable limits
  - Comprehensive audit trail

- **LLM Router**
  - Multi-provider support: OpenAI, Anthropic Claude, Grok, Ollama
  - Automatic fallback on provider failure
  - Token usage tracking
  - Unified interface across providers

- **Memory Agent**
  - Semantic search with Firestore
  - Full provenance tracking
  - Vertex AI Matching Engine integration
  - Audit-ready memory management

- **Verifier Agent**
  - Multi-verifier voting system
  - Consensus-based verification
  - Configurable confidence thresholds
  - LLM-powered reasoning

- **Transformer Agent**
  - Data normalization, filtering, mapping
  - Aggregation operations
  - Pipeline support

- **Exporter Agent**
  - JSON, CSV, XML export formats
  - Configurable formatting
  - Size tracking

## 🏗️ Architecture

```
app/
├── api/v1/              # API endpoints
│   ├── health.py        # Health checks
│   ├── memory.py        # Memory operations
│   ├── verify.py        # Verification
│   ├── transform.py     # Transformations
│   ├── export.py        # Export operations
│   ├── llm.py          # LLM completions
│   └── maker.py        # MAKER execution
├── core/               # Core components
│   ├── config.py       # Configuration
│   ├── maker.py        # MAKER implementation
│   ├── llm_router.py   # LLM routing
│   └── security.py     # Security utilities
├── agents/             # Agent implementations
│   ├── memory/         # Memory agent
│   ├── verifier/       # Verifier agent
│   ├── transformer/    # Transformer agent
│   └── exporter/       # Exporter agent
├── models/             # Pydantic schemas
│   └── schemas.py
└── main.py            # FastAPI application
```

## 🔧 Configuration

All configuration is done via environment variables. See `.env.example` for all available options.

Key configuration areas:
- **Google Cloud**: Project ID, region, Firestore database
- **Vertex AI**: Location, Matching Engine endpoints
- **LLM Providers**: API keys for OpenAI, Anthropic, Grok
- **MAKER**: k-value, timeout, concurrency limits
- **Memory**: Search parameters, similarity thresholds

## 🧪 Testing

```bash
# Run all tests
make test

# Run specific test file
pytest tests/test_maker.py -v

# Run with coverage
pytest --cov=app --cov-report=html
```

## 📊 API Documentation

Once running, access:
- **OpenAPI/Swagger UI**: http://localhost:8080/docs
- **ReDoc**: http://localhost:8080/redoc
- **OpenAPI JSON**: http://localhost:8080/openapi.json

### Key Endpoints

#### Health
- `GET /api/v1/health` - Health check
- `GET /api/v1/ready` - Readiness check

#### Memory
- `POST /api/v1/memory/store` - Store content with provenance
- `POST /api/v1/memory/search` - Semantic search
- `GET /api/v1/memory/{id}` - Get by ID
- `PUT /api/v1/memory/{id}/provenance` - Update provenance

#### Verification
- `POST /api/v1/verify/` - Verify content with voting

#### Transform
- `POST /api/v1/transform/` - Transform data

#### Export
- `POST /api/v1/export/` - Export data

#### LLM
- `POST /api/v1/llm/complete` - Generate completion
- `GET /api/v1/llm/providers` - List providers

#### MAKER
- `POST /api/v1/maker/execute` - Execute MAKER

## 🔒 Security

This is a production-grade, audit-ready system with:

- **Type Safety**: Full type hints, Pydantic validation
- **Input Sanitization**: All user inputs sanitized
- **Secret Management**: Google Cloud Secret Manager
- **Audit Trail**: Structured logging, provenance tracking
- **Non-root Container**: Docker runs as non-root user
- **CORS Configuration**: Configurable allowed origins
- **Health Checks**: Liveness and readiness probes

## 🛠️ Development

### Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Type check
make type-check

# Run all checks
make lint && make type-check && make test
```

### Docker

```bash
# Build image
make docker-build

# Run container
make docker-run
```

## 📈 Production Deployment

### Google Cloud Run

The application is optimized for Cloud Run with:
- Automatic scaling
- Secret Manager integration
- Health check configuration
- Structured logging to Cloud Logging
- Firestore for persistence
- Vertex AI for embeddings

### CI/CD

GitHub Actions workflow automatically:
1. Runs linting and type checking
2. Executes test suite
3. Builds Docker image
4. Deploys to Cloud Run (on main branch)

## 📚 Tech Stack

- **Framework**: FastAPI 0.109+
- **Python**: 3.11+
- **Validation**: Pydantic v2
- **Logging**: structlog
- **Testing**: pytest, pytest-asyncio
- **Type Checking**: mypy
- **Linting**: ruff
- **Container**: Docker
- **Cloud**: Google Cloud Run, Firestore, Vertex AI, Secret Manager
- **LLMs**: OpenAI, Anthropic, Grok, Ollama

## 🤝 Contributing

This is a production system prioritizing:
1. **Correctness** over speed
2. **Type safety** is non-negotiable
3. **Audit trail** for all operations
4. **Testing** all changes
5. **Documentation** updates

## 📄 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

Based on the MDAP framework by Meyerson et al. (2025).

---

**Production Status**: This is a regulated, audit-ready system. All changes must maintain compliance with type safety, logging, and security requirements.
