# Piston Audio

Turn your Raspberry Pi into a Bluetooth audio receiver with a sleek web interface for managing connections and audio settings.

## Features

- **Bluetooth A2DP Sink**: Stream high-quality audio from your phone, tablet, or computer
- **Web-based UI**: Manage pairing, devices, and audio settings from any browser
- **Pairing Confirmation**: Approve or reject pairing requests with passkey display
- **Audio Output Selection**: Switch between audio outputs (HDMI, 3.5mm jack, USB DAC)
- **Volume Control**: Adjust volume with a responsive slider (up to 150% boost)
- **Auto-reconnect**: Trusted devices automatically reconnect
- **Dark Mode**: Automatic dark/light theme based on system preference

## Screenshots

```
+------------------------------------------+
|  Piston Audio                     [gear] |
+------------------------------------------+
|                                          |
|  [toggle] Discoverable                   |
|           Allow devices to find and pair |
|                                          |
|  Devices                        [refresh]|
|  +------------------------------------+  |
|  | [phone] iPhone 15           [conn] |  |
|  | 12:34:56:78:9A:BC                  |  |
|  +------------------------------------+  |
|                                          |
|  Audio                                   |
|  Output: [Built-in Audio Analog   v]     |
|                                          |
|  Volume                                  |
|  [mute] [==========|--------] 65%        |
|                                          |
+------------------------------------------+

Default port: 7654
```

## Quick Start

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/AlexProgrammerDE/piston-audio-ui/main/install.sh | sudo bash
```

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/AlexProgrammerDE/piston-audio-ui.git
cd piston-audio-ui

# Run the installer
sudo ./install.sh

# Start the service
sudo systemctl start piston-audio
```

### Run for Development

```bash
# Clone and enter directory
git clone https://github.com/AlexProgrammerDE/piston-audio-ui.git
cd piston-audio-ui

# Run with virtual environment
./run.sh

# Or with custom options
./run.sh --port 3000 --name "My Speaker"
```

## Usage

### Accessing the Web UI

Open a browser and navigate to:
```
http://<raspberry-pi-ip>:7654
```

Find your Pi's IP address with:
```bash
hostname -I
```

### Pairing a Device

1. Enable "Discoverable" mode in the web UI
2. On your phone/device, scan for Bluetooth devices
3. Select "Piston Audio" from the list
4. Confirm the pairing in the web UI when prompted
5. Start playing music!

### Command Line Options

```
piston-audio [OPTIONS]

Options:
  --host TEXT     Host to bind to (default: 0.0.0.0)
  --port INTEGER  Port to listen on (default: 7654)
  --name TEXT     Bluetooth device name (default: Piston Audio)
  --debug         Enable debug logging
```

### Updating

To update an existing installation:
```bash
cd piston-audio-ui
git pull
sudo ./install.sh --update
```

Or simply re-run the installer (it detects existing installations):
```bash
sudo ./install.sh
```

## Requirements

### Hardware
- Raspberry Pi 3/4/5/Zero 2 W (or any Pi with Bluetooth)
- Audio output (3.5mm jack, HDMI, USB DAC, or I2S DAC/HAT)

### Software
- Raspberry Pi OS Lite (Bookworm or Trixie recommended)
- Python 3.9+
- BlueZ 5.x
- PipeWire + WirePlumber (preferred, auto-installed)

### Tested On
- Raspberry Pi OS Lite (64-bit) - Bookworm
- Raspberry Pi OS Lite (64-bit) - Trixie
- Raspberry Pi 4 Model B
- Raspberry Pi Zero 2 W

## Configuration

### Bluetooth Settings

Edit `/etc/bluetooth/main.conf`:

```ini
[General]
Name = Piston Audio
Class = 0x200414  # Audio device class
DiscoverableTimeout = 0
PairableTimeout = 0

[Policy]
AutoEnable = true
```

### Audio Output

Select audio output in the web UI or via command line:

```bash
# List available outputs
pactl list sinks short

# Set default output
pactl set-default-sink <sink-name>
```

### Service Management

```bash
# Start the service
sudo systemctl start piston-audio

# Stop the service
sudo systemctl stop piston-audio

# View logs
sudo journalctl -u piston-audio -f

# Enable at boot (done automatically by installer)
sudo systemctl enable piston-audio

# Check status
sudo systemctl status piston-audio
```

## How It Works

### Bluetooth A2DP Sink

The Raspberry Pi is configured as a Bluetooth A2DP sink (audio receiver). When a phone or computer connects:

1. **BlueZ** handles the Bluetooth connection and pairing
2. **PipeWire** receives the A2DP audio stream
3. **WirePlumber** automatically routes audio to the default output
4. **Piston Audio UI** provides web-based management

### Headless Operation

For Raspberry Pi OS Lite (headless), the installer configures:

- **Console autologin**: Required for PipeWire user services
- **User lingering**: Keeps services running without active login
- **WirePlumber config**: Disables seat monitoring for headless use

## Architecture

```
piston-audio-ui/
├── src/
│   ├── __init__.py
│   ├── main.py              # Application entry point
│   ├── bluetooth_agent.py   # D-Bus Bluetooth agent
│   ├── audio_manager.py     # PipeWire/PulseAudio control
│   └── ui.py                # NiceGUI web interface
├── install.sh               # Installation script
├── run.sh                   # Development runner
├── requirements.txt         # Python dependencies
└── README.md
```

### Components

1. **Bluetooth Agent** (`bluetooth_agent.py`)
   - Implements BlueZ Agent1 interface via D-Bus
   - Handles pairing requests (PIN, passkey, confirmation)
   - Manages device trust and auto-connect

2. **Audio Manager** (`audio_manager.py`)
   - Detects PipeWire or PulseAudio backend
   - Lists and switches audio sinks
   - Controls volume and mute

3. **Web UI** (`ui.py`)
   - NiceGUI-based responsive interface
   - Real-time device status updates
   - Pairing confirmation dialogs

## Troubleshooting

### Bluetooth Not Working

```bash
# Check Bluetooth service
sudo systemctl status bluetooth

# Restart Bluetooth
sudo systemctl restart bluetooth

# Check adapter
bluetoothctl show
```

### No Audio Output

```bash
# Check PulseAudio/PipeWire
pactl info

# List audio sinks
pactl list sinks

# Check Bluetooth audio module
pactl list modules | grep bluetooth
```

### Device Not Connecting

```bash
# Check paired devices
bluetoothctl paired-devices

# Trust a device manually
bluetoothctl trust <MAC-ADDRESS>
```

### Web UI Not Loading

```bash
# Check service status
sudo systemctl status piston-audio

# Check port
ss -tlnp | grep 8080

# Check firewall
sudo ufw status
```

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/AlexProgrammerDE/piston-audio-ui.git
cd piston-audio-ui

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run with hot reload
python -m src.main --debug
```

### Running Tests

```bash
pytest tests/
```

### Code Style

```bash
# Format code
ruff format .

# Lint
ruff check .

# Type check
mypy src/
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [NiceGUI](https://nicegui.io/) - Python web UI framework
- [BlueZ](http://www.bluez.org/) - Linux Bluetooth stack
- [dbus-fast](https://github.com/Bluetooth-Devices/dbus-fast) - Fast D-Bus library
- [rpi-audio-receiver](https://github.com/nicokaiser/rpi-audio-receiver) - Inspiration for Bluetooth setup
