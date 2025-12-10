.PHONY: help install dev test lint format type-check clean run docker-build docker-run deploy

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install dependencies
	pip install -r requirements.txt

dev:  ## Run development server with auto-reload
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

test:  ## Run tests with coverage
	pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html

lint:  ## Run linting
	ruff check app/ tests/

format:  ## Format code
	ruff format app/ tests/

type-check:  ## Run type checking
	mypy app/

clean:  ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage

run:  ## Run production server
	python -m uvicorn app.main:app --host 0.0.0.0 --port 8080

docker-build:  ## Build Docker image
	docker build -t verisynth-research-os:latest .

docker-run:  ## Run Docker container
	docker run -p 8080:8080 --env-file .env verisynth-research-os:latest

deploy:  ## Deploy to Google Cloud Run
	gcloud run deploy verisynth-research-os \
		--source . \
		--region us-central1 \
		--platform managed \
		--allow-unauthenticated \
		--set-env-vars ENVIRONMENT=production

deploy-with-secrets:  ## Deploy with Secret Manager
	gcloud run deploy verisynth-research-os \
		--source . \
		--region us-central1 \
		--platform managed \
		--allow-unauthenticated \
		--set-env-vars ENVIRONMENT=production \
		--set-secrets=OPENAI_API_KEY=openai-api-key:latest,ANTHROPIC_API_KEY=anthropic-api-key:latest
