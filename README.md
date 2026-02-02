# Jebao Pump MQTT Bridge

A Python service that connects Jebao DMP series aquarium wavemaker pumps to Home Assistant via MQTT.

## Features

- **Multiple pump support** - Connect up to 5-7 pumps from one Raspberry Pi
- **Home Assistant auto-discovery** - Pumps automatically appear in HA
- **Real-time status updates** - Changes from physical controller sync instantly
- **Full control** - Power, flow, frequency, mode, and feed mode
- **Auto-reconnect** - Handles BLE disconnections gracefully

## Requirements

- Raspberry Pi Zero W, 3, 4, or 5 (or any Linux device with Bluetooth)
- Python 3.9+
- MQTT Broker (Mosquitto recommended)
- Home Assistant with MQTT integration

## Local Development (Mac/Linux)

For testing on your development machine before deploying to Pi.

### 1. Setup Python Environment

```bash
cd jebao-mqtt
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run MQTT Broker Locally

**Option A: Docker (easiest)**
```bash
# Start Mosquitto MQTT broker
docker run -d --name mosquitto \
  -p 1883:1883 \
  eclipse-mosquitto:2 \
  mosquitto -c /mosquitto-no-auth.conf

# Verify it's running
docker logs mosquitto
```

**Option B: Homebrew (macOS)**
```bash
brew install mosquitto
brew services start mosquitto

# Or run in foreground
mosquitto -v
```

**Option C: apt (Linux)**
```bash
sudo apt install mosquitto mosquitto-clients
sudo systemctl start mosquitto
```

### 3. Configure for Local Testing

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml`:
```yaml
mqtt:
  host: localhost      # Local broker
  port: 1883
  username: null       # No auth for local testing
  password: null

pumps:
  - name: "Test Pump"
    mac: "XX:XX:XX:XX:XX:XX"  # Your pump's MAC
```

### 4. Find Your Pump

```bash
python3 scan.py
```

### 5. Run the Bridge

```bash
python3 jebao_mqtt_bridge.py --config config.yaml --debug
```

### 6. Test MQTT Messages

In another terminal, subscribe to see messages:

```bash
# Docker
docker exec mosquitto mosquitto_sub -t 'jebao/#' -v

# Or if mosquitto-clients installed locally
mosquitto_sub -h localhost -t 'jebao/#' -v
```

Send test commands:

```bash
# Turn pump on
mosquitto_pub -h localhost -t 'jebao/test_pump/power/set' -m 'ON'

# Set flow to 50%
mosquitto_pub -h localhost -t 'jebao/test_pump/flow/set' -m '50'

# Enable feed mode
mosquitto_pub -h localhost -t 'jebao/test_pump/feed/set' -m 'ON'
```

### 7. Cleanup

```bash
# Stop Docker MQTT broker
docker stop mosquitto && docker rm mosquitto

# Or Homebrew
brew services stop mosquitto

# Deactivate venv
deactivate
```

### Note for Mac Users

Docker on Mac **cannot access Bluetooth**, so you must run the bridge natively with Python (not in Docker) to connect to real pumps. Docker is only useful for:
- Running the MQTT broker
- Testing the Docker image builds correctly
- CI/CD pipelines

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone repo
git clone https://github.com/nateshannonio/jebao-mqtt.git ~/jebao-mqtt
cd ~/jebao-mqtt

# Run setup script
chmod +x scripts/setup-docker.sh
./scripts/setup-docker.sh

# Edit config with your pump MAC address
cp config.yaml.example config.yaml
nano config.yaml

# Start container
docker compose up -d

# View logs
docker compose logs -f
```

### Option 2: Direct Install (Native)

```bash
# Clone repo
git clone https://github.com/nateshannonio/jebao-mqtt.git ~/jebao-mqtt
cd ~/jebao-mqtt

# Run setup script
chmod +x scripts/setup.sh
./scripts/setup.sh
```

---

## Docker Deployment

### Why Docker?

| Benefit | Description |
|---------|-------------|
| **Isolation** | App runs in container, doesn't affect host |
| **Easy updates** | Pull new image, restart container |
| **Portability** | Same setup works on Pi, NAS, server |
| **Auto-restart** | Built-in restart policies |
| **Watchtower** | Auto-update when you push to GitHub |

### BLE Access in Docker

Docker needs access to the host's Bluetooth stack. Two options:

**Option 1: Privileged mode (recommended for Pi)**
```yaml
network_mode: host
privileged: true
volumes:
  - /var/run/dbus:/var/run/dbus:ro
```

**Option 2: Minimal privileges (may not work everywhere)**
```yaml
network_mode: host
cap_add:
  - NET_ADMIN
  - NET_RAW
devices:
  - /dev/hci0:/dev/hci0
volumes:
  - /var/run/dbus:/var/run/dbus:ro
```

### Auto-Update with Watchtower

Automatically pull and restart when you push new images:

```bash
# Start with Watchtower
docker compose -f docker-compose.yml -f docker-compose.watchtower.yml up -d
```

Watchtower checks every 5 minutes for new images and auto-updates.

### Using Pre-built Images

Once you push to GitHub, images are built automatically for:
- `linux/amd64` (PC/Server)
- `linux/arm64` (Pi 4/5 64-bit)
- `linux/arm/v7` (Pi 3/4 32-bit)
- `linux/arm/v6` (Pi Zero W)

```yaml
# In docker-compose.yml, replace 'build: .' with:
image: ghcr.io/nateshannonio/jebao-mqtt:latest
```

### Docker Commands

```bash
# Start
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f

# Restart
docker compose restart

# Update (if using pre-built image)
docker compose pull
docker compose up -d

# Shell into container
docker compose exec jebao-mqtt /bin/bash

# Check status
docker compose ps
```

---

## Native Installation

### 1. Install Dependencies

```bash
# Scan for BLE devices
sudo bluetoothctl
scan on
# Look for "XPG-GAgent-XXXX" - note the MAC address
scan off
exit
```

Or use the included scan script:
```bash
python3 -c "
import asyncio
from bleak import BleakScanner
async def scan():
    devices = await BleakScanner.discover()
    for d in devices:
        if 'XPG' in (d.name or '') or 'Jebao' in (d.name or ''):
            print(f'{d.address} - {d.name}')
asyncio.run(scan())
"
```

### 3. Configure

Edit `config.yaml`:

```yaml
mqtt:
  host: 192.168.1.100    # Your MQTT broker IP
  port: 1883
  username: mqtt_user    # If authentication required
  password: mqtt_pass

pumps:
  - name: "Wavemaker 1"
    mac: "AA:BB:CC:DD:EE:FF"  # Your pump's MAC
```

### 4. Test Run

```bash
python3 jebao_mqtt_bridge.py --config config.yaml --debug
```

You should see:
```
Connected to MQTT broker
[Wavemaker 1] Connecting to AA:BB:CC:DD:EE:FF...
[Wavemaker 1] Connected
[Wavemaker 1] Login successful
[Wavemaker 1] Published MQTT discovery
```

### 5. Install as Service

```bash
# Copy service file
sudo cp jebao-mqtt.service /etc/systemd/system/

# Edit if your username isn't 'pi' or paths differ
sudo nano /etc/systemd/system/jebao-mqtt.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable jebao-mqtt
sudo systemctl start jebao-mqtt

# Check status
sudo systemctl status jebao-mqtt

# View logs
journalctl -u jebao-mqtt -f
```

## Home Assistant

Once the bridge is running, the pump(s) will automatically appear in Home Assistant via MQTT discovery.

### Entities Created

For each pump, you'll get:

| Entity | Type | Description |
|--------|------|-------------|
| `switch.wavemaker_1_power` | Switch | Turn pump on/off |
| `switch.wavemaker_1_feed_mode` | Switch | 10-minute feed mode |
| `number.wavemaker_1_flow` | Number | Flow 30-100% |
| `number.wavemaker_1_frequency` | Number | Wave frequency 5-20s |
| `select.wavemaker_1_mode` | Select | Wave mode |
| `binary_sensor.wavemaker_1_connected` | Binary Sensor | BLE connection status |

### Example Automations

**Feed time automation:**
```yaml
automation:
  - alias: "Aquarium Feed Time"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.wavemaker_1_feed_mode
```

**Night mode (reduce flow):**
```yaml
automation:
  - alias: "Aquarium Night Mode"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.wavemaker_1_flow
        data:
          value: 40
```

## Multiple Pumps

Add more pumps to `config.yaml`:

```yaml
pumps:
  - name: "Left Wavemaker"
    mac: "AA:BB:CC:DD:EE:01"
    
  - name: "Right Wavemaker"
    mac: "AA:BB:CC:DD:EE:02"
    
  - name: "Return Pump"
    mac: "AA:BB:CC:DD:EE:03"
```

## Troubleshooting

### Can't connect to pump

1. Make sure pump is powered on and BLE is active (LED blinking)
2. Check MAC address is correct
3. Ensure no other device (phone app) is connected to the pump
4. Try restarting Bluetooth: `sudo systemctl restart bluetooth`

### MQTT connection fails

1. Verify MQTT broker is running: `systemctl status mosquitto`
2. Check broker IP and port in config
3. Verify credentials if using authentication

### Pump disconnects frequently

1. Move Raspberry Pi closer to the pump
2. Check for WiFi interference (2.4GHz can interfere with BLE)
3. Consider a USB Bluetooth adapter with better antenna

### View debug logs

```bash
# Run manually with debug
python3 jebao_mqtt_bridge.py --debug

# Or check service logs
journalctl -u jebao-mqtt -f
```

## Full Maintenance Stack

For production use, run the maintenance setup script to add:

```bash
sudo ./scripts/setup-maintenance.sh
```

This installs:

| Component | Purpose | Port/Location |
|-----------|---------|---------------|
| **Unattended-upgrades** | Auto OS security updates | N/A |
| **Hardware Watchdog** | Auto-reboot if frozen | N/A |
| **Glances** | Web-based system monitor | :61208 |
| **Node Exporter** | Prometheus metrics | :9100 |
| **Log Rotation** | Prevent disk fill | N/A |
| **System Monitor** | Health checks + alerts | Every 5 min |
| **Boot Notification** | Alert when Pi reboots | N/A |

### Configure Alerting

Edit environment variables for your preferred notification service:

```bash
cp .env.example .env
nano .env
```

**Options:**
- **ntfy.sh** (recommended) - Free, simple, no account needed
- **Pushover** - $5 one-time, very reliable
- **Telegram** - Free, requires bot setup
- **Home Assistant Webhook** - Direct HA integration

Test alerts:
```bash
source .env
./scripts/alert.sh "Test Alert" "Hello from Pi!"
```

### Monitoring URLs

After setup, access:
- **Glances UI**: `http://<pi-ip>:61208`
- **Prometheus metrics**: `http://<pi-ip>:9100/metrics`

### Home Assistant Integration

See `docs/home-assistant-integration.yaml` for:
- Glances integration setup
- Webhook automation for alerts  
- Example dashboard cards
- Auto-restart automation

## GitOps / Automated Maintenance

This project is designed for easy maintenance via GitHub.

### Repository Structure

```
jebao-mqtt/
├── jebao_mqtt_bridge.py    # Main application
├── config.yaml             # Your local config (edit this)
├── requirements.txt        # Python dependencies
├── jebao-mqtt.service      # Systemd service
├── scripts/
│   ├── setup.sh            # Initial Pi setup
│   ├── update.sh           # Auto-update script
│   ├── healthcheck.sh      # Health monitoring
│   ├── jebao-mqtt-update.service
│   └── jebao-mqtt-update.timer
└── .github/
    └── workflows/
        └── ci.yml          # GitHub Actions CI/CD
```

### Initial Setup (New Pi)

```bash
# Clone your GitHub repo
git clone https://github.com/nateshannonio/jebao-mqtt.git ~/jebao-mqtt
cd ~/jebao-mqtt

# Enable pre-commit security hook
git config core.hooksPath .githooks

# Run setup script
chmod +x scripts/setup.sh
./scripts/setup.sh

# Copy templates and edit (NEVER edit .example files directly!)
cp config.yaml.example config.yaml
cp .env.example .env
nano config.yaml

# Start service
sudo systemctl enable jebao-mqtt
sudo systemctl start jebao-mqtt
```

### ⚠️ Security Notes

**Never commit secrets to git!** The repo includes safeguards:

1. **`.gitignore`** - Excludes `config.yaml`, `.env`, and common secret patterns
2. **Pre-commit hook** - Blocks commits containing potential secrets
3. **Example files** - Use `*.example` as templates, copy before editing

Enable the pre-commit hook:
```bash
git config core.hooksPath .githooks
```

If you accidentally commit secrets:
```bash
# Remove from history (requires force push)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch config.yaml' HEAD
git push --force
```

Then rotate any exposed credentials.

### Enable Auto-Updates

The Pi will check GitHub every 15 minutes and auto-update:

```bash
sudo systemctl enable jebao-mqtt-update.timer
sudo systemctl start jebao-mqtt-update.timer

# Check timer status
systemctl list-timers | grep jebao
```

### Workflow

1. **Develop locally** or edit on GitHub
2. **Push to main branch**
3. **Pi automatically pulls** changes (within 15 min)
4. **Service restarts** with new code
5. **Rollback** happens automatically if service fails to start

### Manual Update

```bash
cd ~/jebao-mqtt
./scripts/update.sh
```

### Check Update Logs

```bash
cat /var/log/jebao-mqtt-update.log
```

### GitHub Actions (Optional)

The included workflow runs linting on every push. To enable auto-deploy via SSH:

1. Add secrets to your GitHub repo:
   - `PI_HOST`: Your Pi's IP or hostname
   - `PI_USER`: SSH username (usually `pi`)
   - `PI_SSH_KEY`: Private SSH key

2. Uncomment the deploy job in `.github/workflows/ci.yml`

## Protocol Details

See `jebao_protocol_final.md` for the complete reverse-engineered BLE protocol documentation.

## License

MIT License - Use at your own risk. Not affiliated with Jebao.
