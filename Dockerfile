# Dockerfile for VeriSynthOS Agents
# Multi-stage build for efficient containerization

FROM python:3.10-slim as base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build arguments
ARG AGENT_FILE
ARG PORT=8000

# Environment variables
ENV AGENT_FILE=${AGENT_FILE}
ENV PORT=${PORT}
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get(f'http://localhost:${PORT}/health')"

# Run the agent
CMD uvicorn ${AGENT_FILE%.py}:app --host 0.0.0.0 --port ${PORT}
