#!/bin/bash
# scripts/healthcheck.sh
#
# Health check script - can be called by monitoring systems
# Exit 0 = healthy, Exit 1 = unhealthy

SERVICE_NAME="jebao-mqtt"
MQTT_HOST="${MQTT_HOST:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"

# Check 1: Service is running
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "UNHEALTHY: Service not running"
    exit 1
fi

# Check 2: Process is responding (not zombied)
PID=$(systemctl show -p MainPID --value "$SERVICE_NAME")
if [ "$PID" = "0" ] || [ ! -d "/proc/$PID" ]; then
    echo "UNHEALTHY: Process not found"
    exit 1
fi

# Check 3: MQTT broker is reachable (optional)
if command -v mosquitto_pub &> /dev/null; then
    if ! timeout 5 mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "jebao/healthcheck" -m "ping" 2>/dev/null; then
        echo "WARNING: MQTT broker unreachable"
        # Don't fail on this - broker might be separate
    fi
fi

# Check 4: Memory usage isn't excessive
MEM_PERCENT=$(ps -p "$PID" -o %mem --no-headers | tr -d ' ')
if (( $(echo "$MEM_PERCENT > 50" | bc -l) )); then
    echo "WARNING: High memory usage: ${MEM_PERCENT}%"
fi

echo "HEALTHY: Service running (PID: $PID, MEM: ${MEM_PERCENT}%)"
exit 0
