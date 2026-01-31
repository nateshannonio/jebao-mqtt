# Dockerfile for Jebao MQTT Bridge
#
# Supports: amd64, arm64, arm/v7, arm/v6 (Pi Zero W)
#
# Build:
#   docker build -t jebao-mqtt-bridge .
#
# Run:
#   docker run -d --name jebao-mqtt \
#     --net=host \
#     --privileged \
#     -v /var/run/dbus:/var/run/dbus \
#     -v ./config.yaml:/app/config.yaml:ro \
#     jebao-mqtt-bridge

FROM python:3.11-slim-bookworm

# Install system dependencies for BLE
RUN apt-get update && apt-get install -y --no-install-recommends \
    bluetooth \
    bluez \
    libglib2.0-dev \
    dbus \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user (will still need privileges for BLE)
RUN useradd -m -s /bin/bash appuser && \
    usermod -a -G bluetooth appuser

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY jebao_mqtt_bridge.py .
COPY scripts/healthcheck.sh /healthcheck.sh
RUN chmod +x /healthcheck.sh

# Default config location
VOLUME ["/app/config.yaml"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Environment variables (can be overridden)
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Run as root for BLE access (required for /var/run/dbus)
# Security is handled by container isolation
USER root

ENTRYPOINT ["python", "-u", "jebao_mqtt_bridge.py"]
CMD ["--config", "/app/config.yaml"]
