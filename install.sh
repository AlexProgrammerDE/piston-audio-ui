#!/bin/bash
#
# Piston Audio - Installation Script
# 
# This script installs all dependencies and configures the Raspberry Pi
# for Bluetooth audio streaming.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root (sudo ./install.sh)"
        exit 1
    fi
}

# Detect OS
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        VERSION=$VERSION_ID
    else
        error "Cannot detect OS"
        exit 1
    fi
    
    info "Detected OS: $OS $VERSION"
}

# Install system dependencies
install_system_deps() {
    info "Updating package lists..."
    apt-get update
    
    info "Installing system dependencies..."
    apt-get install -y \
        bluez \
        bluez-tools \
        python3 \
        python3-pip \
        python3-venv \
        python3-dbus \
        python3-gi \
        libdbus-1-dev \
        libglib2.0-dev \
        pulseaudio \
        pulseaudio-module-bluetooth \
        pipewire \
        pipewire-pulse \
        pipewire-audio-client-libraries \
        libspa-0.2-bluetooth
        
    success "System dependencies installed"
}

# Configure Bluetooth
configure_bluetooth() {
    info "Configuring Bluetooth..."
    
    # Create BlueZ configuration directory
    mkdir -p /etc/bluetooth
    
    # Configure BlueZ main.conf
    cat > /etc/bluetooth/main.conf << 'EOF'
[General]
Name = Piston Audio
Class = 0x200414
DiscoverableTimeout = 0
PairableTimeout = 0
FastConnectable = true

[Policy]
AutoEnable = true
EOF

    # Configure BlueZ audio.conf for A2DP sink
    cat > /etc/bluetooth/audio.conf << 'EOF'
[General]
Enable = Source,Sink,Media,Socket
EOF

    # Enable Bluetooth service
    systemctl enable bluetooth
    systemctl restart bluetooth
    
    success "Bluetooth configured"
}

# Configure PulseAudio/PipeWire for Bluetooth
configure_audio() {
    info "Configuring audio for Bluetooth..."
    
    # Create PulseAudio configuration for system-wide mode
    mkdir -p /etc/pulse
    
    # Configure PulseAudio to load Bluetooth modules
    if [ ! -f /etc/pulse/default.pa.d/bluetooth.pa ]; then
        mkdir -p /etc/pulse/default.pa.d
        cat > /etc/pulse/default.pa.d/bluetooth.pa << 'EOF'
# Bluetooth audio support
.ifexists module-bluetooth-discover.so
load-module module-bluetooth-discover
.endif

.ifexists module-bluetooth-policy.so
load-module module-bluetooth-policy
.endif
EOF
    fi
    
    # Configure BlueALSA as fallback (optional, for systems without PulseAudio)
    if command -v bluealsa &> /dev/null; then
        info "BlueALSA detected, configuring..."
        systemctl enable bluealsa || true
    fi
    
    success "Audio configured"
}

# Create virtual environment and install Python dependencies
install_python_deps() {
    info "Setting up Python virtual environment..."
    
    # Get the script directory
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # Create virtual environment
    python3 -m venv "$SCRIPT_DIR/venv"
    
    # Activate and install dependencies
    source "$SCRIPT_DIR/venv/bin/activate"
    
    pip install --upgrade pip
    pip install -r "$SCRIPT_DIR/requirements.txt"
    
    deactivate
    
    success "Python dependencies installed"
}

# Install systemd service
install_service() {
    info "Installing systemd service..."
    
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # Create systemd service file
    cat > /etc/systemd/system/piston-audio.service << EOF
[Unit]
Description=Piston Audio - Bluetooth Audio Receiver
After=bluetooth.target network.target sound.target
Wants=bluetooth.target
Requires=dbus.socket

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python -m src.main --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

# Security settings
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/run /tmp
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    systemctl daemon-reload
    
    success "Systemd service installed"
}

# Configure D-Bus permissions
configure_dbus() {
    info "Configuring D-Bus permissions..."
    
    # Create D-Bus policy for Piston Audio
    cat > /etc/dbus-1/system.d/piston-audio.conf << 'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="root">
    <allow own="org.piston.bluetooth"/>
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.Agent1"/>
    <allow send_interface="org.bluez.AgentManager1"/>
    <allow send_interface="org.bluez.Adapter1"/>
    <allow send_interface="org.bluez.Device1"/>
    <allow send_interface="org.freedesktop.DBus.ObjectManager"/>
    <allow send_interface="org.freedesktop.DBus.Properties"/>
  </policy>
</busconfig>
EOF

    # Reload D-Bus
    systemctl reload dbus || true
    
    success "D-Bus permissions configured"
}

# Enable and start services
enable_services() {
    info "Enabling services..."
    
    # Enable Bluetooth
    systemctl enable bluetooth
    
    # Enable Piston Audio (but don't start yet)
    systemctl enable piston-audio
    
    success "Services enabled"
}

# Print final instructions
print_instructions() {
    echo ""
    echo "=============================================="
    echo -e "${GREEN}Installation Complete!${NC}"
    echo "=============================================="
    echo ""
    echo "To start Piston Audio:"
    echo "  sudo systemctl start piston-audio"
    echo ""
    echo "To view logs:"
    echo "  sudo journalctl -u piston-audio -f"
    echo ""
    echo "To access the web interface:"
    echo "  http://$(hostname -I | awk '{print $1}'):8080"
    echo ""
    echo "To run manually (for testing):"
    echo "  cd $(pwd)"
    echo "  ./run.sh"
    echo ""
    echo "Your Raspberry Pi will appear as 'Piston Audio'"
    echo "in Bluetooth device lists."
    echo ""
}

# Main installation
main() {
    echo "=============================================="
    echo "  Piston Audio Installer"
    echo "=============================================="
    echo ""
    
    check_root
    detect_os
    
    install_system_deps
    configure_bluetooth
    configure_audio
    install_python_deps
    configure_dbus
    install_service
    enable_services
    
    print_instructions
}

# Run main
main "$@"
