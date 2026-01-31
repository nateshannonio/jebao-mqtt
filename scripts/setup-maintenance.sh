#!/bin/bash
# scripts/setup-maintenance.sh
#
# Sets up comprehensive monitoring, auto-updates, and alerting
# for Raspberry Pi running Jebao MQTT Bridge
#
# Run with: sudo ./scripts/setup-maintenance.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
    log_error "Please run as root: sudo $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PI_USER="${SUDO_USER:-pi}"

echo "=========================================="
echo "Pi Maintenance Stack Setup"
echo "=========================================="
echo ""
echo "User: $PI_USER"
echo "Repo: $REPO_DIR"
echo ""

# ============================================
# Helper: install a systemd service from template
# ============================================
install_service() {
    local src="$1"
    local name=$(basename "$src")

    sed -e "s|JEBAO_USER|$PI_USER|g" \
        -e "s|JEBAO_REPO_DIR|$REPO_DIR|g" \
        "$src" | tee "/etc/systemd/system/$name" > /dev/null
}

# ============================================
# 1. UNATTENDED UPGRADES
# ============================================
log_info "Setting up unattended-upgrades..."

apt-get update -qq
apt-get install -y --no-install-recommends unattended-upgrades apt-listchanges

cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}";
    "${distro_id}:${distro_codename}-security";
    "${distro_id}:${distro_codename}-updates";
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
EOF

cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
EOF

log_info "Unattended-upgrades configured"

# ============================================
# 2. HARDWARE WATCHDOG
# ============================================
log_info "Setting up hardware watchdog..."

apt-get install -y --no-install-recommends watchdog

# Enable in boot config
for config_file in /boot/firmware/config.txt /boot/config.txt; do
    if [ -f "$config_file" ] && ! grep -q "dtparam=watchdog=on" "$config_file"; then
        echo "dtparam=watchdog=on" >> "$config_file"
        break
    fi
done

cat > /etc/watchdog.conf << EOF
watchdog-device = /dev/watchdog
interval = 10
max-load-15 = 25
min-memory = 1
watchdog-timeout = 15
test-binary = $REPO_DIR/scripts/healthcheck.sh
log-dir = /var/log/watchdog
realtime = yes
priority = 1
EOF

mkdir -p /var/log/watchdog
systemctl enable watchdog
systemctl start watchdog || true

log_info "Hardware watchdog configured"

# ============================================
# 3. LOG ROTATION
# ============================================
log_info "Setting up log rotation..."

cat > /etc/logrotate.d/jebao-mqtt << 'EOF'
/var/log/jebao-mqtt*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
EOF

cat > /etc/logrotate.d/pi-aggressive << 'EOF'
/var/log/syslog /var/log/messages /var/log/daemon.log
/var/log/kern.log /var/log/auth.log {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
}
EOF

log_info "Log rotation configured"

# ============================================
# 4. SYSTEM MONITORING - Glances
# ============================================
log_info "Setting up Glances monitoring..."

pip3 install glances bottle --break-system-packages 2>/dev/null || \
pip3 install glances bottle

cat > /etc/systemd/system/glances.service << 'EOF'
[Unit]
Description=Glances System Monitor
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/glances -w -p 61208 --disable-plugin docker
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable glances
systemctl start glances || true

log_info "Glances running on port 61208"

# ============================================
# 5. SYSTEM MONITOR TIMER
# ============================================
log_info "Setting up system monitor timer..."

# Make scripts executable
chmod +x "$SCRIPT_DIR/alert.sh"
chmod +x "$SCRIPT_DIR/system-monitor.sh"
chmod +x "$SCRIPT_DIR/backup.sh"
chmod +x "$SCRIPT_DIR/healthcheck.sh"

cat > /etc/systemd/system/system-monitor.service << EOF
[Unit]
Description=System Health Monitor

[Service]
Type=oneshot
User=$PI_USER
ExecStart=$REPO_DIR/scripts/system-monitor.sh
EOF

cat > /etc/systemd/system/system-monitor.timer << 'EOF'
[Unit]
Description=Run system monitor every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable system-monitor.timer
systemctl start system-monitor.timer

log_info "System monitor running every 5 minutes"

# ============================================
# 6. BOOT NOTIFICATION
# ============================================
log_info "Setting up boot notification..."

cat > /etc/systemd/system/boot-notify.service << EOF
[Unit]
Description=Send notification on boot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$PI_USER
ExecStartPre=/bin/sleep 30
ExecStart=$REPO_DIR/scripts/alert.sh "🟢 Pi Booted" "$(hostname) is online"
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable boot-notify

log_info "Boot notification enabled"

# ============================================
# 7. SWAP OPTIMIZATION (for Pi Zero)
# ============================================
log_info "Optimizing swap..."

sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile 2>/dev/null || true
dphys-swapfile setup 2>/dev/null || true
dphys-swapfile swapon 2>/dev/null || true
echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
sysctl -p /etc/sysctl.d/99-swappiness.conf 2>/dev/null || true

log_info "Swap optimized"

# ============================================
# 8. UPDATE LOG
# ============================================
touch /var/log/jebao-mqtt-update.log
chown "$PI_USER:$PI_USER" /var/log/jebao-mqtt-update.log

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Services installed:"
echo "  ✅ Unattended-upgrades (auto OS security patches)"
echo "  ✅ Hardware watchdog (auto-reboot if frozen)"
echo "  ✅ Log rotation (prevents disk fill)"
echo "  ✅ Glances (web UI on port 61208)"
echo "  ✅ System monitor (health checks every 5 min)"
echo "  ✅ Boot notifications"
echo "  ✅ Swap optimization"
echo ""
echo "Next steps:"
echo ""
echo "1. Configure alerting:"
echo "   nano $REPO_DIR/.env"
echo "   Set NTFY_TOPIC, PUSHOVER_TOKEN, or TELEGRAM_TOKEN"
echo ""
echo "2. Test alerts:"
echo "   $REPO_DIR/scripts/alert.sh 'Test' 'Hello from Pi!'"
echo ""
echo "3. View monitoring:"
echo "   http://$(hostname -I 2>/dev/null | awk '{print $1}'):61208"
echo ""
echo "4. Check timers:"
echo "   systemctl list-timers"
echo ""
echo "5. Reboot to enable watchdog:"
echo "   sudo reboot"
echo ""
