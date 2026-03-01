#!/bin/bash
# =========================================================
# Tableau Extension Development - Quick Start
# =========================================================
# Starts tunnels and configures everything dynamically for
# testing the Tableau Extension inside Tableau Cloud.
#
# Usage:
#   ./start-extension-dev.sh
#   ./start-extension-dev.sh --stop
#
# The script will:
#   1. Stop and restart Docker services (clean state)
#   2. Create tunnel for backend API (port 8000)
#   3. Create tunnel for extension HTML (port 8080)
#   4. Update app.js with backend tunnel URL
#   5. Update .trex with extension tunnel URL
#   6. Update CORS and FULLY RESTART backend
# =========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Config files
ENV_FILE=".env"
APP_JS="tableau-extension/src/app.js"
TREX_FILE="tableau-extension/ai-analytics-agent.trex"
BACKEND_LOG="/tmp/cf_backend.log"
EXTENSION_LOG="/tmp/cf_extension.log"

cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    pkill -f "python3 -m http.server 8080" 2>/dev/null || true
    
    # Restore original files if backups exist
    [ -f "${APP_JS}.original" ] && cp "${APP_JS}.original" "$APP_JS" && echo "  Restored app.js"
    [ -f "${TREX_FILE}.original" ] && cp "${TREX_FILE}.original" "$TREX_FILE" && echo "  Restored .trex"
    
    echo -e "${GREEN}Cleanup complete.${NC}"
}

# Handle --stop argument
if [ "$1" == "--stop" ]; then
    cleanup
    exit 0
fi

# Handle Ctrl+C gracefully
trap cleanup EXIT

echo ""
echo -e "${CYAN}==========================================================${NC}"
echo -e "${CYAN}   🔌 Tableau Extension Development Mode${NC}"
echo -e "${CYAN}==========================================================${NC}"
echo ""

# =========================================================
# Step 1: Clean restart Docker services
# =========================================================
echo -e "${BLUE}[1/7]${NC} Stopping Docker services for clean restart..."
docker compose down 2>/dev/null || true

echo -e "${BLUE}[2/7]${NC} Starting Docker services..."
docker compose up -d

echo -n "  Waiting for backend"
for i in {1..60}; do
    if curl -s http://localhost:8000/api/v1/live > /dev/null 2>&1; then
        echo ""
        break
    fi
    echo -n "."
    sleep 1
done
echo -e "${GREEN}✓ Docker services running${NC}"

# =========================================================
# Step 3: Start extension demo server
# =========================================================
echo -e "${BLUE}[3/7]${NC} Starting extension demo server (port 8080)..."
pkill -f "python3 -m http.server 8080" 2>/dev/null || true
sleep 1
cd tableau-extension/src && python3 -m http.server 8080 > /dev/null 2>&1 &
cd "$SCRIPT_DIR"
sleep 2
echo -e "${GREEN}✓ Demo server running on port 8080${NC}"

# =========================================================
# Step 4: Create tunnels
# =========================================================
echo -e "${BLUE}[4/7]${NC} Creating Cloudflare tunnels..."

# Kill any existing tunnels
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

# Clear old logs
> "$BACKEND_LOG"
> "$EXTENSION_LOG"

# Retry tunnel creation up to 3 times
BACKEND_TUNNEL=""
EXTENSION_TUNNEL=""

for ATTEMPT in 1 2 3; do
    echo -e "  ${YELLOW}Attempt ${ATTEMPT}/3...${NC}"

    # Clear logs for this attempt
    > "$BACKEND_LOG"
    > "$EXTENSION_LOG"
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    sleep 2

    # Start backend tunnel (port 8000)
    cloudflared tunnel --url http://localhost:8000 > "$BACKEND_LOG" 2>&1 &
    BACKEND_PID=$!

    # Start extension tunnel (port 8080)
    cloudflared tunnel --url http://localhost:8080 > "$EXTENSION_LOG" 2>&1 &
    EXTENSION_PID=$!

    # Wait for tunnels to establish
    echo -n "  Waiting for tunnels"
    for i in {1..25}; do
        BACKEND_TUNNEL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$BACKEND_LOG" 2>/dev/null | head -1)
        EXTENSION_TUNNEL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$EXTENSION_LOG" 2>/dev/null | head -1)
        if [ -n "$BACKEND_TUNNEL" ] && [ -n "$EXTENSION_TUNNEL" ]; then
            echo ""
            break
        fi
        echo -n "."
        sleep 1
    done

    # Check if both tunnels are up
    if [ -n "$BACKEND_TUNNEL" ] && [ -n "$EXTENSION_TUNNEL" ]; then
        break
    fi

    echo -e "\n  ${YELLOW}Tunnel attempt ${ATTEMPT} failed, retrying...${NC}"
    
    # Show error from logs for debugging
    grep -i "error\|failed" "$BACKEND_LOG" 2>/dev/null | tail -1 || true
    
    BACKEND_TUNNEL=""
    EXTENSION_TUNNEL=""
    sleep 3
done

if [ -z "$BACKEND_TUNNEL" ] || [ -z "$EXTENSION_TUNNEL" ]; then
    echo -e "\n${RED}✗ Failed to create tunnels after 3 attempts. Check logs:${NC}"
    echo "  Backend: $BACKEND_LOG"
    echo "  Extension: $EXTENSION_LOG"
    exit 1
fi

echo -e "${GREEN}✓ Backend tunnel:   ${BACKEND_TUNNEL}${NC}"
echo -e "${GREEN}✓ Extension tunnel: ${EXTENSION_TUNNEL}${NC}"

# =========================================================
# Step 5: Backup and update app.js
# =========================================================
echo -e "${BLUE}[5/7]${NC} Updating app.js with backend URL..."

# Backup original if not already backed up
[ ! -f "${APP_JS}.original" ] && cp "$APP_JS" "${APP_JS}.original"

# Update API_URL in app.js
sed -i "s|API_URL:.*|API_URL: '${BACKEND_TUNNEL}/api/v1',|" "$APP_JS"
echo -e "${GREEN}✓ Updated app.js${NC}"

# =========================================================
# Step 6: Backup and update .trex file
# =========================================================
echo -e "${BLUE}[6/7]${NC} Updating .trex with extension URL..."

# Backup original if not already backed up
[ ! -f "${TREX_FILE}.original" ] && cp "$TREX_FILE" "${TREX_FILE}.original"

# Update URL in .trex file
sed -i "s|<url>https://[^<]*</url>|<url>${EXTENSION_TUNNEL}/index.html</url>|" "$TREX_FILE"
echo -e "${GREEN}✓ Updated .trex file${NC}"

# =========================================================
# Step 7: Update CORS and FULLY RESTART backend
# =========================================================
echo -e "${BLUE}[7/7]${NC} Updating CORS and restarting backend..."

# Build new CORS string with all required origins
NEW_CORS="https://10ax.online.tableau.com,http://localhost:8080,http://localhost:8000,${BACKEND_TUNNEL},${EXTENSION_TUNNEL}"

# Update .env file
sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=${NEW_CORS}|" "$ENV_FILE"

# FULL restart of backend to pick up new CORS (not just docker restart)
echo -e "  ${YELLOW}Restarting backend with new CORS settings...${NC}"
docker compose stop backend > /dev/null 2>&1
docker compose up -d backend > /dev/null 2>&1

# Wait for backend to be healthy
echo -n "  Waiting for backend"
for i in {1..30}; do
    if curl -s http://localhost:8000/api/v1/live > /dev/null 2>&1; then
        echo ""
        break
    fi
    echo -n "."
    sleep 1
done
echo -e "${GREEN}✓ Backend restarted with updated CORS${NC}"

# Verify CORS is working
echo -n "  Verifying CORS..."
CORS_CHECK=$(curl -s -I -X OPTIONS "${BACKEND_TUNNEL}/api/v1/live" \
  -H "Origin: ${EXTENSION_TUNNEL}" \
  -H "Access-Control-Request-Method: POST" 2>&1 | grep -i "access-control-allow-origin" || echo "")

if [ -n "$CORS_CHECK" ]; then
    echo -e " ${GREEN}✓${NC}"
else
    echo -e " ${YELLOW}(could not verify, but should work)${NC}"
fi

# =========================================================
# Done! Print instructions
# =========================================================
echo ""
echo -e "${CYAN}==========================================================${NC}"
echo -e "${GREEN}   ✅ Extension Development Mode Ready!${NC}"
echo -e "${CYAN}==========================================================${NC}"
echo ""
echo -e "  ${YELLOW}Backend API:${NC}"
echo -e "    ${BACKEND_TUNNEL}/api/v1"
echo ""
echo -e "  ${YELLOW}Extension HTML:${NC}"
echo -e "    ${EXTENSION_TUNNEL}/index.html"
echo ""
echo -e "  ${CYAN}Test locally:${NC}"
echo -e "    http://localhost:8080/demo.html"
echo ""
echo -e "  ${RED}⚠️  IMPORTANT - First time setup:${NC}"
echo -e "    Before installing the extension, you must add BOTH URLs to Tableau Cloud"
echo -e "    (Settings → Extensions → Enable Specific Extensions):"
echo ""
echo -e "      1. Extension URL: ${YELLOW}${EXTENSION_TUNNEL}${NC}"
echo -e "      2. Backend API:  ${YELLOW}${BACKEND_TUNNEL}${NC}"
echo ""
echo -e "    This ensures Tableau allows the network connection between them."
echo ""
echo -e "  ${CYAN}Install in Tableau Cloud:${NC}"
echo -e "    1. Open your dashboard in Edit mode"
echo -e "    2. Drag an 'Extension' object onto the dashboard"
echo -e "    3. Click 'Add from File' → select:"
echo -e "       ${YELLOW}tableau-extension/ai-analytics-agent.trex${NC}"
echo -e "    4. The AI chat will appear in your dashboard!"
echo ""
echo -e "  ${RED}Press Ctrl+C to stop and restore original files${NC}"
echo ""

# Keep script running to maintain tunnels
echo -e "${BLUE}Tunnels running... Press Ctrl+C to stop.${NC}"
wait
