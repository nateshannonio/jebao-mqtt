#!/bin/bash
# scripts/system-monitor.sh
#
# System health monitor - runs periodically and sends alerts if issues detected
# Intended to be run by systemd timer every 5 minutes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALERT_SCRIPT="$SCRIPT_DIR/alert.sh"
STATE_FILE="/tmp/system-monitor-state"

# Thresholds
DISK_THRESHOLD=85        # Alert if disk usage > 85%
MEMORY_THRESHOLD=85      # Alert if memory usage > 85%
TEMP_THRESHOLD=75        # Alert if CPU temp > 75°C
LOAD_THRESHOLD=2         # Alert if load > 2 (for Pi Zero)

# Get current values
DISK_USAGE=$(df / | awk 'NR==2 {print int($5)}')
MEMORY_USAGE=$(free | awk '/Mem:/ {printf "%.0f", $3/$2 * 100}')
CPU_TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{printf "%.0f", $1/1000}')
LOAD_AVG=$(awk '{print $1}' /proc/loadavg)

# Track state to avoid repeated alerts
touch "$STATE_FILE"

send_alert_once() {
    local key="$1"
    local title="$2"
    local message="$3"

    if ! grep -q "^$key$" "$STATE_FILE" 2>/dev/null; then
        echo "$key" >> "$STATE_FILE"
        "$ALERT_SCRIPT" "$title" "$message"
    fi
}

clear_alert() {
    local key="$1"
    sed -i "/^$key$/d" "$STATE_FILE" 2>/dev/null || true
}

# Check disk
if [ "$DISK_USAGE" -gt "$DISK_THRESHOLD" ]; then
    send_alert_once "disk_high" "⚠️ Disk Space Low" "Disk usage: ${DISK_USAGE}%"
else
    clear_alert "disk_high"
fi

# Check memory
if [ "$MEMORY_USAGE" -gt "$MEMORY_THRESHOLD" ]; then
    send_alert_once "memory_high" "⚠️ Memory Low" "Memory usage: ${MEMORY_USAGE}%"
else
    clear_alert "memory_high"
fi

# Check temperature
if [ -n "$CPU_TEMP" ] && [ "$CPU_TEMP" -gt "$TEMP_THRESHOLD" ]; then
    send_alert_once "temp_high" "🌡️ CPU Hot" "Temperature: ${CPU_TEMP}°C"
else
    clear_alert "temp_high"
fi

# Check load
if [ "$(echo "$LOAD_AVG > $LOAD_THRESHOLD" | bc)" -eq 1 ]; then
    send_alert_once "load_high" "📈 High Load" "Load average: ${LOAD_AVG}"
else
    clear_alert "load_high"
fi

# Check if jebao service or container is running
if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q "jebao"; then
    clear_alert "jebao_down"
elif systemctl is-active --quiet jebao-mqtt 2>/dev/null; then
    clear_alert "jebao_down"
else
    send_alert_once "jebao_down" "🔴 Jebao Bridge Down" "Service/container not running!"
fi

# Output for logging
echo "$(date '+%Y-%m-%d %H:%M:%S') - Disk: ${DISK_USAGE}%, Mem: ${MEMORY_USAGE}%, Temp: ${CPU_TEMP:-N/A}°C, Load: ${LOAD_AVG}"
