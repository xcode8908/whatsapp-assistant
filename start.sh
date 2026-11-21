#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 STARTING WHATSAPP AI ASSISTANT & WAHA BUNDLE"
echo "================================================="

# Set environment defaults for WAHA
export WAHA_PORT=3000
export WHATSAPP_DEFAULT_ENGINE=NOWEB
export WHATSAPP_SWAGGER_ENABLED=false
export WAHA_DASHBOARD_ENABLED=false
export WAHA_EVENTS_DOWNLOAD_MEDIA=false
export WAHA_API_DOWNLOAD_MEDIA=false
export WHATSAPP_HOOK_URL="http://localhost:${PORT:-10000}/api/webhook/waha"
export WHATSAPP_HOOK_EVENTS="message,session.status"

# Connect WAHA session storage to Supabase PostgreSQL if provided
if [ -n "$DATABASE_URL" ]; then
    echo "🔗 Supabase Database URL detected. Setting WAHA PostgreSQL session storage..."
    export WHATSAPP_SESSIONS_POSTGRESQL_URL="$DATABASE_URL"
fi

# 1. Start WAHA in background
echo "Starting WAHA engine..."
/entrypoint.sh &
WAHA_PID=$!

# 2. Wait for WAHA to be responsive
echo "Waiting for WAHA to initialize on localhost:3000..."
MAX_RETRIES=30
COUNT=0
until curl -s http://localhost:3000/api/server/version > /dev/null 2>&1; do
    sleep 2
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "⚠️ WAHA is taking longer to start, continuing to Python launch..."
        break
    fi
done

echo "✅ WAHA engine is UP!"

# Auto-start default session
curl -s -X POST http://localhost:3000/api/sessions \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${WAHA_SESSION:-default}\"}" > /dev/null 2>&1 || true

# 3. Start Python FastAPI & Telegram Bot on Render's assigned PORT
echo "Starting Python Assistant Backend on port ${PORT:-10000}..."
cd /app/assistant
exec python3 main.py
