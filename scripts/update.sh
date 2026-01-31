#!/bin/bash
# scripts/update.sh
#
# Auto-update script for Jebao MQTT Bridge
# Pulls latest from GitHub and restarts service if changed

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="jebao-mqtt"
LOG_FILE="/var/log/jebao-mqtt-update.log"
BRANCH="main"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

cd "$REPO_DIR"

# Fetch latest changes
log "Fetching updates from origin/$BRANCH..."
git fetch origin "$BRANCH"

# Check if there are updates
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date ($LOCAL)"
    exit 0
fi

log "Updates available: $LOCAL -> $REMOTE"

# Pull changes
log "Pulling changes..."
git pull origin "$BRANCH"

# Install any new dependencies
if [ -f "requirements.txt" ]; then
    log "Updating Python dependencies..."
    pip3 install -r requirements.txt --break-system-packages --quiet 2>/dev/null || \
    pip3 install -r requirements.txt --quiet
fi

# Restart the service
log "Restarting $SERVICE_NAME service..."
sudo systemctl restart "$SERVICE_NAME"

# Verify service started
sleep 5
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Service restarted successfully"
    
    # Optional: Send notification (uncomment if using ntfy.sh or similar)
    # curl -s -d "Jebao MQTT Bridge updated to $(git rev-parse --short HEAD)" ntfy.sh/your-topic
else
    log "ERROR: Service failed to start!"
    log "Rolling back..."
    git checkout "$LOCAL"
    sudo systemctl restart "$SERVICE_NAME"
    exit 1
fi

log "Update complete: now at $(git rev-parse --short HEAD)"
