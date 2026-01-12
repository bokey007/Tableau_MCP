#!/bin/bash
# =========================================================
# Regression Test Runner
# =========================================================
# This script runs the comprehensive regression test suite
# with LLM-as-Judge evaluation.
#
# Usage:
#   ./run_tests.sh
#
# Required Environment Variables:
#   OPENAI_API_KEY - Your OpenAI API key for the judge model
#
# Optional:
#   BACKEND_URL - Default: http://localhost:8000/api/v1
# =========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧪 Tableau MCP Agent - Regression Test Suite"
echo "============================================="
echo ""

# Check for OPENAI_API_KEY
if [ -z "$OPENAI_API_KEY" ]; then
    # Try to load from parent .env file
    if [ -f "../.env" ]; then
        echo "Loading API key from ../.env"
        export $(grep -E "^OPENAI_API_KEY=" ../.env | xargs)
    fi
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ Error: OPENAI_API_KEY not set"
    echo "   Set it with: export OPENAI_API_KEY='your-key'"
    echo "   Or add it to the .env file in the project root"
    exit 1
fi

# Default backend URL
export BACKEND_URL="${BACKEND_URL:-http://localhost:8000/api/v1}"
echo "📡 Backend URL: $BACKEND_URL"
echo "🤖 Judge Model: gpt-4.5-preview"
echo ""

# Check if backend is reachable
echo "Checking backend connectivity..."
if ! curl -s "${BACKEND_URL}/live" > /dev/null 2>&1; then
    echo "❌ Backend not reachable at $BACKEND_URL"
    echo "   Make sure the backend is running"
    exit 1
fi
echo "✅ Backend is up!"
echo ""

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install dependencies
echo "Installing test dependencies..."
pip install -q -r requirements.txt

# Run tests
echo ""
echo "Running regression tests..."
echo "============================================="
python regression_test_suite.py

# Deactivate venv
deactivate
