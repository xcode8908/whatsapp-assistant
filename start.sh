#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 STARTING WHATSAPP AI ASSISTANT & WAHA BUNDLE"
echo "================================================="

# External port assigned by Render for Python FastAPI
RENDER_PORT="${PORT:-10000}"

# 1. Start WAHA inside /app directory strictly isolated on internal port 3000
echo "Starting WAHA engine on internal port 3000..."
(
    cd /app
    export PORT=3000
    export WHATSAPP_API_PORT=3000
    export WAHA_API_KEY="silentxop_waha_secure_key_2026"
    export WHATSAPP_DEFAULT_ENGINE=NOWEB
    export WHATSAPP_NOWEB_WA_VERSION=auto-web
    export WHATSAPP_START_SESSION=default
    export WHATSAPP_RESTART_ALL_SESSIONS=True
    export WHATSAPP_SWAGGER_ENABLED=false
    export WAHA_DASHBOARD_ENABLED=false
    export WAHA_EVENTS_DOWNLOAD_MEDIA=false
    export WAHA_API_DOWNLOAD_MEDIA=false
    export WHATSAPP_HOOK_URL="http://127.0.0.1:${RENDER_PORT}/api/webhook/waha"
    export WHATSAPP_HOOK_EVENTS="message,session.status"
    exec /entrypoint.sh
) &

# 2. Start Python FastAPI & Telegram Bot on Render's external port
echo "Starting Python Assistant Backend on port ${RENDER_PORT}..."
export PORT="$RENDER_PORT"
cd /app/assistant
exec python3 main.py
