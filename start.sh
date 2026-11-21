#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 STARTING WHATSAPP AI ASSISTANT & WAHA BUNDLE"
echo "================================================="

# Save Render's assigned external port for Python FastAPI
RENDER_PORT="${PORT:-10000}"

# Set environment defaults for WAHA on internal port 3000
export WHATSAPP_API_PORT=3000
export WHATSAPP_DEFAULT_ENGINE=NOWEB
export WHATSAPP_SWAGGER_ENABLED=false
export WAHA_DASHBOARD_ENABLED=false
export WAHA_EVENTS_DOWNLOAD_MEDIA=false
export WAHA_API_DOWNLOAD_MEDIA=false
export WHATSAPP_HOOK_URL="http://localhost:${RENDER_PORT}/api/webhook/waha"
export WHATSAPP_HOOK_EVENTS="message,session.status"

# Connect WAHA session storage to Supabase PostgreSQL if provided
if [ -n "$DATABASE_URL" ]; then
    echo "🔗 Supabase Database URL detected. Setting WAHA PostgreSQL session storage..."
    export WHATSAPP_SESSIONS_POSTGRESQL_URL="$DATABASE_URL"
fi

# 1. Start WAHA inside /app directory on internal port 3000
echo "Starting WAHA engine from /app on port 3000..."
(PORT=3000 WHATSAPP_API_PORT=3000 cd /app && /entrypoint.sh) &
WAHA_PID=$!

# 2. Wait for WAHA to be responsive on internal port 3000
echo "Waiting for WAHA to initialize on localhost:3000..."
MAX_RETRIES=40
COUNT=0
until curl -s http://localhost:3000/api/server/version > /dev/null 2>&1; do
    sleep 2
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "⚠️ WAHA initialization took longer, proceeding to Python launch..."
        break
    fi
done

echo "✅ WAHA engine is UP on port 3000!"

# 3. Start Python FastAPI & Telegram Bot on Render's assigned external port
echo "Starting Python Assistant Backend on port ${RENDER_PORT}..."
export PORT="$RENDER_PORT"
cd /app/assistant
exec python3 main.py
