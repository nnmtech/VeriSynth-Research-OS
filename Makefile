# Makefile — top level (replace your current one)
.PHONY: dev dev-enterprise test lint typecheck deploy install clean help

# PORT defaults to 7000 if not set
PORT ?= 7000

# Install dependencies first
install:
	pip install -r requirements.txt

dev:
	uvicorn run_memory_agent:app --reload --port=$(PORT)

dev-enterprise:
	uvicorn run_memory_agent_enterprise:app --reload --port=$(PORT)

test:
	pytest -vv

lint:
	ruff check .

typecheck:
	mypy .

deploy:
	gcloud run deploy verisynthos-research-os \
		--source . \
		--region=us-central1 \
		--allow-unauthenticated \
		--port=8080
