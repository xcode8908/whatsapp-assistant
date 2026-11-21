FROM devlikeapro/waha:latest

USER root

# Install Python 3, pip, curl and dos2unix
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/assistant/requirements.txt
RUN pip3 install --no-cache-dir -r /app/assistant/requirements.txt --break-system-packages

# Copy all assistant source files into /app/assistant
COPY . /app/assistant/

# Convert any CRLF to Linux LF and set execution permissions
RUN dos2unix /app/assistant/start.sh && chmod +x /app/assistant/start.sh

# Environment settings
ENV PORT=10000
ENV WAHA_PORT=3000
ENV WHATSAPP_DEFAULT_ENGINE=NOWEB
ENV WHATSAPP_SWAGGER_ENABLED=false
ENV WAHA_DASHBOARD_ENABLED=false
ENV WAHA_EVENTS_DOWNLOAD_MEDIA=false
ENV WAHA_API_DOWNLOAD_MEDIA=false

EXPOSE 10000

# Start both WAHA and Python Assistant
CMD ["/app/assistant/start.sh"]
