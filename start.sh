#!/bin/bash
# =========================================================
# Tableau MCP Agent - Startup Script
# =========================================================
# This script starts the entire application stack cleanly.
#
# Usage:
#   ./start.sh          - Start all services
#   ./start.sh --reset  - Stop, rebuild, and start fresh
#   ./start.sh --stop   - Stop all services
# =========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Handle arguments
case "$1" in
    --stop)
        print_status "Stopping all services..."
        docker compose down
        print_success "All services stopped."
        exit 0
        ;;
    --reset)
        print_status "Stopping all services..."
        docker compose down
        print_status "Rebuilding containers..."
        docker compose build --no-cache
        ;;
esac

echo ""
echo "==========================================================="
echo "   🚀 Tableau MCP Agent - Starting Application"
echo "==========================================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    print_error ".env file not found!"
    print_warning "Copy .env.example to .env and configure your settings."
    exit 1
fi

# Stop any running containers first
print_status "Stopping any running containers..."
docker compose down 2>/dev/null || true

# Start services
print_status "Starting all services..."
docker compose up -d

# Wait for services to be healthy
print_status "Waiting for services to be healthy..."

# Wait for postgres
echo -n "  Postgres: "
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
        echo -e "${GREEN}Ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

# Wait for backend
echo -n "  Backend:  "
for i in {1..60}; do
    if curl -s http://localhost:8000/api/v1/live > /dev/null 2>&1; then
        echo -e "${GREEN}Ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

# Wait for frontend
echo -n "  Frontend: "
for i in {1..30}; do
    if curl -s http://localhost:8501 > /dev/null 2>&1; then
        echo -e "${GREEN}Ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

# Start demo server for Tableau Extension testing
print_status "Starting demo server for Tableau Extension..."
pkill -f "python3 -m http.server 8080" 2>/dev/null || true
cd tableau-extension/src && python3 -m http.server 8080 > /dev/null 2>&1 &
cd "$SCRIPT_DIR"
sleep 2
echo -n "  Demo:     "
if curl -s http://localhost:8080/demo.html > /dev/null 2>&1; then
    echo -e "${GREEN}Ready${NC}"
else
    echo -e "${YELLOW}Check manually${NC}"
fi

# Final status
echo ""
print_status "Checking service status..."
docker compose ps

echo ""
echo "==========================================================="
print_success "Application is ready!"
echo "==========================================================="
echo ""
echo "  📊 Streamlit UI:  http://localhost:8501"
echo "  🔧 Backend API:   http://localhost:8000"
echo "  📚 API Docs:      http://localhost:8000/docs"
echo "  🎨 Extension Demo: http://localhost:8080/demo.html"
echo ""
echo "  Tableau Extension:"
echo "    - Test in browser: http://localhost:8080/demo.html"
echo "    - Install TREX:    tableau-extension/src/tableau-mcp.trex"
echo ""
echo "  To view logs: docker compose logs -f"
echo "  To stop:      ./start.sh --stop"
echo ""
