#!/bin/bash
# VeriSynthOS Memory Agent - Enterprise Edition Quick Start

echo "=================================="
echo "VeriSynthOS Memory Agent"
echo "Enterprise Edition Installer"
echo "=================================="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✅ Python $PYTHON_VERSION detected"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
echo "This includes:"
echo "  - FastAPI & Uvicorn (web server)"
echo "  - tiktoken (token-aware chunking)"
echo "  - Google Cloud libraries (Firestore, Vision, Tasks, Storage)"
echo "  - NumPy (vector similarity)"
echo ""
read -p "Press Enter to continue..."

pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Dependencies installed successfully!"
else
    echo ""
    echo "❌ Installation failed. Please check errors above."
    exit 1
fi

echo ""
echo "=================================="
echo "Installation Complete!"
echo "=================================="
echo ""
echo "🚀 Quick Start Commands:"
echo ""
echo "  1. Start Basic Edition:"
echo "     make dev PORT=7000"
echo ""
echo "  2. Start Enterprise Edition (Recommended):"
echo "     make dev-enterprise PORT=7000"
echo ""
echo "  3. View API docs:"
echo "     http://localhost:7000/docs"
echo ""
echo "=================================="
echo "📚 Documentation:"
echo "=================================="
echo ""
echo "  - README.md - Overview and configuration"
echo "  - ENTERPRISE_FEATURES.md - All 20 enterprise features"
echo "  - LINE_BY_LINE_VERIFICATION.md - Implementation proof"
echo "  - IMPLEMENTATION_COMPLETE.md - Complete report"
echo "  - RAG_ARCHITECTURE.md - Technical architecture"
echo ""
echo "=================================="
echo "🎯 Next Steps:"
echo "=================================="
echo ""
echo "  1. Set environment variables (optional for GCP):"
echo "     export WEBHOOK_URL=\"https://your-domain.com/webhook/drive\""
echo "     export CLOUD_TASKS_QUEUE=\"memory-ingestion-queue\""
echo "     export ME_INDEX_ID=\"projects/.../indexes/...\""
echo ""
echo "  2. Start the server:"
echo "     make dev-enterprise"
echo ""
echo "  3. Test ingestion:"
echo "     curl -X POST http://localhost:7000/ingest \\"
echo "       -H \"Content-Type: application/json\" \\"
echo "       -d '{\"local_path\": \".\", \"recursive\": true}'"
echo ""
echo "  4. Test search:"
echo "     curl -X POST http://localhost:7000/search \\"
echo "       -H \"Content-Type: application/json\" \\"
echo "       -d '{\"query\": \"memory agent\", \"use_hybrid\": true}'"
echo ""
echo "=================================="
echo "✨ Ready to go! Run 'make dev-enterprise' to start."
echo "=================================="
