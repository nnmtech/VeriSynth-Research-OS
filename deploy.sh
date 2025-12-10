#!/bin/bash
# VeriSynthOS Agent Deployment Script
# Deploy all agents to Google Cloud Run

set -e

# Configuration
PROJECT_ID=${GCP_PROJECT:-$(gcloud config get-value project)}
REGION=${GCP_REGION:-us-central1}
IMAGE_REGISTRY="gcr.io/$PROJECT_ID"

echo "🚀 VeriSynthOS Agent Deployment"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Build and deploy function
deploy_agent() {
    local AGENT_NAME=$1
    local AGENT_FILE=$2
    local PORT=$3
    local SERVICE_ACCOUNT=$4
    
    echo -e "${BLUE}Deploying $AGENT_NAME...${NC}"
    
    # Build container
    echo "Building Docker image..."
    gcloud builds submit --tag "$IMAGE_REGISTRY/$AGENT_NAME" \
        --project="$PROJECT_ID" \
        --build-arg AGENT_FILE="$AGENT_FILE" \
        --build-arg PORT="$PORT" \
        .
    
    # Deploy to Cloud Run
    echo "Deploying to Cloud Run..."
    gcloud run deploy "$AGENT_NAME" \
        --image "$IMAGE_REGISTRY/$AGENT_NAME" \
        --platform managed \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --service-account "$SERVICE_ACCOUNT" \
        --port "$PORT" \
        --memory 2Gi \
        --cpu 2 \
        --timeout 900 \
        --max-instances 10 \
        --allow-unauthenticated \
        --set-env-vars "GCP_PROJECT=$PROJECT_ID,MAKER_MODE=true"
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$AGENT_NAME" \
        --platform managed \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --format 'value(status.url)')
    
    echo -e "${GREEN}✅ $AGENT_NAME deployed: $SERVICE_URL${NC}"
    echo ""
    
    # Store URL in env file
    echo "${AGENT_NAME}_URL=$SERVICE_URL" >> .env.production
}

# Create .env.production file
rm -f .env.production
touch .env.production

# Deploy agents in dependency order
echo "=== Deploying infrastructure agents ==="
deploy_agent "monitor" "agents.monitor.agent.py" 8006 "monitor-sa@$PROJECT_ID.iam.gserviceaccount.com"
deploy_agent "memory" "agents.memory.main.enterprise.py" 7000 "memory-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo "=== Deploying data agents ==="
deploy_agent "researcher" "agents.researcher.agent.py" 8001 "researcher-sa@$PROJECT_ID.iam.gserviceaccount.com"
deploy_agent "data-retriever" "agents.data_retriever.agent.py" 8003 "data-retriever-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo "=== Deploying processing agents ==="
deploy_agent "verifier" "agents.verifier.agent.py" 8002 "verifier-sa@$PROJECT_ID.iam.gserviceaccount.com"
deploy_agent "transformer" "agents.transformer.agent.py" 8004 "transformer-sa@$PROJECT_ID.iam.gserviceaccount.com"
deploy_agent "exporter" "agents.exporter.agent.py" 8005 "exporter-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo "=== Deploying orchestrator ==="
# Load agent URLs into orchestrator env
source .env.production
deploy_agent "orchestrator" "orchestrator.agent.py" 8000 "orchestrator-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo ""
echo -e "${GREEN}🎉 All agents deployed successfully!${NC}"
echo ""
echo "Agent URLs saved to .env.production"
echo ""
echo "To test the orchestrator:"
echo "  curl -X POST \$(cat .env.production | grep orchestrator_URL | cut -d= -f2)/start_job \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"type\":\"research-and-export\",\"query\":\"AI safety\",\"deliverables\":[\"excel\"]}'"
echo ""
