#!/bin/bash
# scripts/setup-docker.sh
#
# Setup script for running Jebao MQTT Bridge in Docker on Raspberry Pi
# This prepares the host system and starts the container

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "=========================================="
echo "Jebao MQTT Bridge - Docker Setup"
echo "=========================================="
echo ""

# Check if running on Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null && \
   ! grep -q "BCM" /proc/cpuinfo 2>/dev/null; then
    log_warn "This doesn't appear to be a Raspberry Pi"
    log_warn "BLE setup may differ on your system"
fi

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    log_info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    log_warn "Please log out and back in for docker group to take effect"
    log_warn "Then re-run this script"
    exit 0
else
    log_info "Docker already installed: $(docker --version)"
fi

# 2. Install Docker Compose if not present
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_info "Installing Docker Compose..."
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin
else
    log_info "Docker Compose already installed"
fi

# 3. Ensure Bluetooth is available on host
log_info "Checking Bluetooth..."
if ! systemctl is-active --quiet bluetooth; then
    log_info "Starting Bluetooth service..."
    sudo systemctl enable bluetooth
    sudo systemctl start bluetooth
fi

# Check for BLE adapter
if ! hciconfig hci0 2>/dev/null | grep -q "UP RUNNING"; then
    log_info "Bringing up Bluetooth adapter..."
    sudo hciconfig hci0 up || {
        log_error "Failed to bring up Bluetooth adapter"
        log_error "Make sure Bluetooth is enabled in raspi-config"
        exit 1
    }
fi

log_info "Bluetooth adapter:"
hciconfig hci0 | head -3

# 4. Create config from template if not exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$REPO_DIR/config.yaml" ]; then
    log_info "Creating config.yaml from template..."
    cp "$REPO_DIR/config.yaml.example" "$REPO_DIR/config.yaml"
    log_warn "Please edit config.yaml with your pump MAC address and MQTT settings"
    echo ""
    echo "  nano $REPO_DIR/config.yaml"
    echo ""
fi

# 5. Scan for Jebao devices
log_info "Scanning for Jebao devices (10 seconds)..."
echo ""
timeout 10 bluetoothctl scan on &
SCAN_PID=$!
sleep 10
kill $SCAN_PID 2>/dev/null || true
bluetoothctl scan off 2>/dev/null || true

echo ""
log_info "Found devices (look for XPG-GAgent):"
bluetoothctl devices | grep -i "xpg\|jebao\|gizwits" || echo "  No Jebao devices found - make sure pump is powered on"
echo ""

# 6. Build or pull the image
log_info "Building Docker image..."
cd "$REPO_DIR"

if docker compose version &> /dev/null; then
    docker compose build
else
    docker-compose build
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit config with your pump's MAC address:"
echo "   nano $REPO_DIR/config.yaml"
echo ""
echo "2. Start the container:"
echo "   cd $REPO_DIR"
echo "   docker compose up -d"
echo ""
echo "3. View logs:"
echo "   docker compose logs -f"
echo ""
echo "4. Stop:"
echo "   docker compose down"
echo ""
echo "For auto-start on boot, Docker handles this automatically"
echo "with 'restart: unless-stopped' in docker-compose.yml"
echo ""
