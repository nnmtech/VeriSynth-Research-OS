# VeriSynth Research OS - GitHub Copilot Instructions

## Project Overview

VeriSynth Research OS is a production implementation of the Massively Decomposed Agentic Processes (MDAP) framework. This is a regulated, audit-ready system prioritizing correctness, type safety, and production hardening.

## Architecture

- **Framework**: FastAPI with async routes
- **Validation**: Pydantic v2 for all schemas
- **Cloud**: Google Cloud Run + Secret Manager
- **Database**: Firestore native client
- **AI**: Vertex AI + Matching Engine
- **Logging**: structlog for structured logging
- **LLMs**: Multi-provider support (OpenAI, Claude, Grok, Ollama)

## Core Components

### MAKER (app/core/maker.py)
- Implements first_to_ahead_by_k strategy
- Dynamic red-flagging for quality control
- Concurrent agent execution with semaphore control
- Comprehensive logging and error handling

### LLM Router (app/core/llm_router.py)
- Unified interface for multiple LLM providers
- Fallback support across providers
- Token usage tracking
- Error handling and retry logic

### Memory Agent (app/agents/memory/)
- Semantic search with Firestore
- Embedding generation (Vertex AI ready)
- Full provenance tracking for audit compliance
- Vector similarity search

### Verifier Agent (app/agents/verifier/)
- Multi-verifier voting system
- Consensus calculation
- Confidence scoring
- LLM-based verification

## Code Standards

### Type Safety
- Use strict type hints for all functions
- Pydantic models for all data validation
- mypy type checking enabled

### Async Best Practices
- Use async/await for I/O operations
- Proper asyncio task management
- Semaphores for rate limiting

### Logging
- Use structlog for structured logging
- Include context with bind()
- Log at appropriate levels (debug, info, warning, error)

### Error Handling
- Catch specific exceptions
- Log errors with context
- Return appropriate HTTP status codes
- Never expose internal details in production

### Security
- Sanitize all user inputs
- Use Secret Manager for credentials
- Non-root Docker user
- CORS properly configured
- API key validation

## Development Workflow

1. Make changes following type hints
2. Run linting: `make lint`
3. Run type checking: `make type-check`
4. Run tests: `make test`
5. Format code: `make format`

## Testing

- Use pytest with async support
- Mock external dependencies (Firestore, LLMs)
- Test edge cases and error conditions
- Aim for >80% coverage

## Deployment

- Containerized with Docker
- Deploys to Google Cloud Run
- CI/CD via GitHub Actions
- Environment-based configuration

## API Design

- RESTful endpoints
- OpenAPI documentation
- Consistent error responses
- Version prefix (/api/v1)
- Health and readiness checks

## When Adding New Features

1. Define Pydantic models first
2. Implement core logic with type hints
3. Add API endpoints
4. Write tests
5. Update documentation
6. Ensure audit trail (logging + provenance)

## Production Considerations

- This is a regulated system - accuracy matters
- All changes must maintain audit trail
- Type safety is non-negotiable
- Performance metrics should be logged
- Errors must be tracked and analyzed
