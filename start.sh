#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 STARTING WHATSAPP AI ASSISTANT & WAHA BUNDLE"
echo "================================================="

# Save Render external port
RENDER_PORT="${PORT:-10000}"

# Configure WAHA for internal port 3000
export WHATSAPP_API_PORT=3000
export WHATSAPP_DEFAULT_ENGINE=NOWEB
export WHATSAPP_SWAGGER_ENABLED=false
export WAHA_DASHBOARD_ENABLED=false
export WAHA_EVENTS_DOWNLOAD_MEDIA=false
export WAHA_API_DOWNLOAD_MEDIA=false
export WHATSAPP_HOOK_URL="http://localhost:${RENDER_PORT}/api/webhook/waha"
export WHATSAPP_HOOK_EVENTS="message,session.status"

# 1. Start WAHA in background on port 3000
echo "Starting WAHA engine in background on internal port 3000..."
(PORT=3000 WHATSAPP_API_PORT=3000 cd /app && /entrypoint.sh) &

# 2. Start Python FastAPI & Telegram Bot on Render's external port IMMEDIATELY
echo "Starting Python Assistant Backend on port ${RENDER_PORT}..."
export PORT="$RENDER_PORT"
cd /app/assistant
exec python3 main.py
