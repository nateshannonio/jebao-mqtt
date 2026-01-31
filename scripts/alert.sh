#!/bin/bash
# scripts/alert.sh
#
# Send alerts via multiple channels
# Usage: alert.sh "Alert Title" "Alert Message"
#
# Configure by setting environment variables in .env:
#   NTFY_TOPIC, PUSHOVER_TOKEN, PUSHOVER_USER,
#   TELEGRAM_TOKEN, TELEGRAM_CHAT, HA_WEBHOOK

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

TITLE="${1:-Alert}"
MESSAGE="${2:-No message provided}"
HOSTNAME=$(hostname)

# ntfy.sh (free, self-hostable)
if [ -n "$NTFY_TOPIC" ]; then
    curl -s -d "$MESSAGE" \
        -H "Title: $TITLE" \
        -H "Tags: raspberry_pi" \
        "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1
fi

# Pushover
if [ -n "$PUSHOVER_TOKEN" ] && [ -n "$PUSHOVER_USER" ]; then
    curl -s \
        --form-string "token=$PUSHOVER_TOKEN" \
        --form-string "user=$PUSHOVER_USER" \
        --form-string "title=$TITLE" \
        --form-string "message=$MESSAGE" \
        https://api.pushover.net/1/messages.json >/dev/null 2>&1
fi

# Telegram
if [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT" ]; then
    curl -s -X POST \
        "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT" \
        -d "text=🔔 $TITLE

$MESSAGE

📍 $HOSTNAME" >/dev/null 2>&1
fi

# Home Assistant Webhook
if [ -n "$HA_WEBHOOK" ]; then
    curl -s -X POST "$HA_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"title\": \"$TITLE\", \"message\": \"$MESSAGE\", \"host\": \"$HOSTNAME\"}" >/dev/null 2>&1
fi

echo "Alert sent: $TITLE - $MESSAGE"
