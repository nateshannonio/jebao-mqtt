#!/bin/bash
# scripts/setup.sh
#
# Initial setup script for Jebao MQTT Bridge on Raspberry Pi
# Run once after cloning the repository
#
# Usage: ./scripts/setup.sh

set -e

echo "=========================================="
echo "Jebao MQTT Bridge - Initial Setup"
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CURRENT_USER="${SUDO_USER:-$USER}"

echo "User: $CURRENT_USER"
echo "Repo: $REPO_DIR"
echo ""

# ============================================
# Helper: install a systemd service from template
# Replaces JEBAO_USER and JEBAO_REPO_DIR placeholders
# ============================================
install_service() {
    local src="$1"
    local name=$(basename "$src")

    echo "  Installing $name..."
    sed -e "s|JEBAO_USER|$CURRENT_USER|g" \
        -e "s|JEBAO_REPO_DIR|$REPO_DIR|g" \
        "$src" | sudo tee "/etc/systemd/system/$name" > /dev/null
}

echo "1. Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends python3 python3-pip bluetooth bluez

echo ""
echo "2. Installing Python dependencies..."
pip3 install -r "$REPO_DIR/requirements.txt" --break-system-packages 2>/dev/null || \
pip3 install -r "$REPO_DIR/requirements.txt"

echo ""
echo "3. Setting up Bluetooth permissions..."
sudo usermod -a -G bluetooth "$CURRENT_USER"

echo ""
echo "4. Making scripts executable..."
chmod +x "$SCRIPT_DIR"/*.sh
chmod +x "$REPO_DIR/.githooks/pre-commit" 2>/dev/null || true

echo ""
echo "5. Installing systemd services..."
install_service "$REPO_DIR/jebao-mqtt.service"
install_service "$SCRIPT_DIR/jebao-mqtt-update.service"
sudo cp "$SCRIPT_DIR/jebao-mqtt-update.timer" /etc/systemd/system/
sudo systemctl daemon-reload

echo ""
echo "6. Setting up git hooks..."
cd "$REPO_DIR"
git config core.hooksPath .githooks 2>/dev/null || true

echo ""
echo "7. Creating config from template..."
if [ ! -f "$REPO_DIR/config.yaml" ]; then
    cp "$REPO_DIR/config.yaml.example" "$REPO_DIR/config.yaml"
    echo "  Created config.yaml from template"
else
    echo "  config.yaml already exists, skipping"
fi

if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "  Created .env from template"
else
    echo "  .env already exists, skipping"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit your configuration:"
echo "   nano $REPO_DIR/config.yaml"
echo ""
echo "2. Find your pump's MAC address:"
echo "   sudo bluetoothctl"
echo "   scan on"
echo "   # Look for XPG-GAgent-XXXX"
echo ""
echo "3. Test the bridge:"
echo "   python3 $REPO_DIR/jebao_mqtt_bridge.py --config $REPO_DIR/config.yaml --debug"
echo ""
echo "4. Enable and start the service:"
echo "   sudo systemctl enable jebao-mqtt"
echo "   sudo systemctl start jebao-mqtt"
echo ""
echo "5. Enable auto-updates from GitHub (optional):"
echo "   sudo systemctl enable jebao-mqtt-update.timer"
echo "   sudo systemctl start jebao-mqtt-update.timer"
echo ""
echo "6. View status and logs:"
echo "   sudo systemctl status jebao-mqtt"
echo "   journalctl -u jebao-mqtt -f"
echo ""
