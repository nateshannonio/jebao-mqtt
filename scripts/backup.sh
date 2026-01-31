#!/bin/bash
# scripts/backup.sh
#
# Backup important configs to cloud storage
# Requires rclone configured with a remote (gdrive, dropbox, etc)
#
# Setup rclone: rclone config
# Then set RCLONE_REMOTE in .env (e.g., RCLONE_REMOTE=gdrive:pi-backups)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

BACKUP_DIR="/tmp/pi-backup"
BACKUP_NAME="pi-backup-$(hostname)-$(date +%Y%m%d).tar.gz"

# Files to backup
BACKUP_PATHS=(
    "$REPO_DIR/config.yaml"
    "$REPO_DIR/.env"
)

# Optional system files (may need sudo)
if [ -r /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    BACKUP_PATHS+=("/etc/wpa_supplicant/wpa_supplicant.conf")
fi

if [ -z "$RCLONE_REMOTE" ]; then
    echo "RCLONE_REMOTE not set in .env, skipping cloud backup"
    echo "To enable, configure rclone and set RCLONE_REMOTE in .env"
    exit 0
fi

# Create backup
mkdir -p "$BACKUP_DIR"
tar czf "$BACKUP_DIR/$BACKUP_NAME" "${BACKUP_PATHS[@]}" 2>/dev/null

# Upload to cloud
if command -v rclone &> /dev/null; then
    rclone copy "$BACKUP_DIR/$BACKUP_NAME" "$RCLONE_REMOTE"
    echo "Backup uploaded to $RCLONE_REMOTE/$BACKUP_NAME"
else
    echo "rclone not installed. Install with: curl https://rclone.org/install.sh | sudo bash"
fi

# Cleanup
rm -rf "$BACKUP_DIR"
