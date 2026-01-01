#!/bin/bash
#
# Piston Audio - Installation Script
# 
# This script installs all dependencies and configures the Raspberry Pi
# for Bluetooth audio streaming. Safe to re-run for updates.
#
# Supports:
# - Raspberry Pi OS Lite (Bookworm/Trixie based)
# - PipeWire audio backend (recommended)
# - PulseAudio fallback
#
# Usage:
#   Local:  sudo ./install.sh
#   Remote: curl -fsSL https://raw.githubusercontent.com/AlexProgrammerDE/piston-audio-ui/main/install.sh | sudo bash
#

set -e

# Configuration
PISTON_PORT=7654
PISTON_USER="${SUDO_USER:-pi}"
VERSION="1.0.0"
REPO_URL="https://github.com/AlexProgrammerDE/piston-audio-ui.git"
INSTALL_DIR="/opt/piston-audio"

# Determine script directory - handle both local run and curl pipe
if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # Check if we're in the actual repo directory
    if [ -f "$SCRIPT_DIR/requirements.txt" ] && [ -d "$SCRIPT_DIR/src" ]; then
        INSTALL_DIR="$SCRIPT_DIR"
    fi
else
    # Running from curl pipe - will clone to INSTALL_DIR
    SCRIPT_DIR=""
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Print functions
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

step() {
    echo -e "${CYAN}==>${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run as root: sudo ./install.sh"
        exit 1
    fi
}

# Detect OS and version
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME=$NAME
        OS_VERSION=$VERSION_ID
        OS_CODENAME=$VERSION_CODENAME
    else
        error "Cannot detect OS - /etc/os-release not found"
        exit 1
    fi
    
    info "Detected: $OS_NAME ($OS_CODENAME)"
    
    # Check for Raspberry Pi
    if [ -f /proc/device-tree/model ]; then
        PI_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
        info "Hardware: $PI_MODEL"
    fi
    
    # Determine package source based on OS version
    case "$OS_CODENAME" in
        bookworm)
            PIPEWIRE_SOURCE="native"
            info "Using native Bookworm packages"
            ;;
        trixie|testing)
            PIPEWIRE_SOURCE="native"
            info "Using native Trixie packages"
            ;;
        bullseye)
            PIPEWIRE_SOURCE="backports"
            warning "Bullseye detected - will use backports for PipeWire"
            ;;
        *)
            PIPEWIRE_SOURCE="native"
            warning "Unknown OS version, attempting native packages"
            ;;
    esac
}

# Clone or update the repository
setup_project_files() {
    step "Setting up project files..."
    
    # Check if we need to clone
    if [ ! -f "$INSTALL_DIR/requirements.txt" ] || [ ! -d "$INSTALL_DIR/src" ]; then
        info "Cloning Piston Audio repository..."
        
        # Ensure git is installed
        if ! command -v git &> /dev/null; then
            apt-get install -y git
        fi
        
        # Remove incomplete installation if exists
        if [ -d "$INSTALL_DIR" ]; then
            rm -rf "$INSTALL_DIR"
        fi
        
        # Clone the repository
        git clone "$REPO_URL" "$INSTALL_DIR"
        
        success "Repository cloned to $INSTALL_DIR"
    else
        # Update existing repository if it's a git repo
        if [ -d "$INSTALL_DIR/.git" ]; then
            info "Updating existing repository..."
            cd "$INSTALL_DIR"
            git fetch origin
            git reset --hard origin/main 2>/dev/null || git reset --hard origin/master 2>/dev/null || true
            success "Repository updated"
        else
            info "Using existing project files in $INSTALL_DIR"
        fi
    fi
    
    # Ensure proper ownership
    chown -R "$PISTON_USER:$PISTON_USER" "$INSTALL_DIR"
}

# Setup package repositories
setup_repositories() {
    step "Setting up package repositories..."
    
    if [ "$PIPEWIRE_SOURCE" = "backports" ]; then
        # Add backports for Bullseye
        BACKPORTS_FILE="/etc/apt/sources.list.d/bullseye-backports.list"
        if [ ! -f "$BACKPORTS_FILE" ]; then
            echo "deb http://deb.debian.org/debian bullseye-backports main contrib non-free" > "$BACKPORTS_FILE"
            info "Added Bullseye backports repository"
        fi
        
        # Set default release to prevent accidental upgrades
        echo 'APT::Default-Release "stable";' > /etc/apt/apt.conf.d/99defaultrelease
    fi
    
    apt-get update -qq
    success "Repositories configured"
}

# Install system dependencies
install_system_deps() {
    step "Installing system dependencies..."
    
    # Core packages available on all versions
    PACKAGES=(
        bluez
        python3
        python3-pip
        python3-venv
        python3-dbus
        python3-gi
        python3-gi-cairo
        gir1.2-glib-2.0
        libdbus-1-dev
        libglib2.0-dev
        git
        curl
    )
    
    # PipeWire packages (prefer PipeWire over PulseAudio)
    PIPEWIRE_PACKAGES=(
        pipewire
        pipewire-audio-client-libraries
        wireplumber
        libspa-0.2-bluetooth
    )
    
    # Install core packages
    apt-get install -y "${PACKAGES[@]}"
    
    # Install PipeWire packages
    if [ "$PIPEWIRE_SOURCE" = "backports" ]; then
        apt-get install -y -t bullseye-backports "${PIPEWIRE_PACKAGES[@]}" || {
            warning "Backports install failed, trying native packages"
            apt-get install -y "${PIPEWIRE_PACKAGES[@]}" || true
        }
    else
        apt-get install -y "${PIPEWIRE_PACKAGES[@]}" || {
            warning "PipeWire packages not fully available, installing what's possible"
        }
    fi
    
    # Remove PulseAudio if PipeWire is installed (they conflict)
    if command -v pipewire &> /dev/null; then
        if dpkg -l | grep -q "^ii.*pulseaudio "; then
            info "Removing PulseAudio (PipeWire will provide compatibility)"
            apt-get remove -y pulseaudio pulseaudio-module-bluetooth 2>/dev/null || true
        fi
    else
        # Fallback to PulseAudio if PipeWire not available
        warning "PipeWire not available, installing PulseAudio"
        apt-get install -y pulseaudio pulseaudio-module-bluetooth
    fi
    
    success "System dependencies installed"
}

# Configure Bluetooth for A2DP sink
configure_bluetooth() {
    step "Configuring Bluetooth..."
    
    # Backup existing config
    if [ -f /etc/bluetooth/main.conf ] && [ ! -f /etc/bluetooth/main.conf.bak ]; then
        cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak
    fi
    
    # Configure BlueZ main.conf
    cat > /etc/bluetooth/main.conf << 'EOF'
[General]
Name = Piston Audio
Class = 0x200414

# Audio device class breakdown:
# 0x200414 = Audio (Major) + Loudspeaker (Minor) + Audio service class

# Pairing settings
DiscoverableTimeout = 0
PairableTimeout = 0
FastConnectable = true

# Allow re-pairing without user interaction (important for headless)
JustWorksRepairing = always

[Policy]
AutoEnable = true
ReconnectAttempts = 7
ReconnectIntervals = 1,2,4,8,16,32,64
EOF

    # Create input.conf for better device compatibility
    cat > /etc/bluetooth/input.conf << 'EOF'
[General]
UserspaceHID = true
EOF

    # Enable and restart Bluetooth service
    systemctl enable bluetooth
    systemctl restart bluetooth
    
    success "Bluetooth configured for A2DP sink"
}

# Configure PipeWire for Bluetooth audio
configure_pipewire() {
    step "Configuring PipeWire for Bluetooth audio..."
    
    # Create WirePlumber Bluetooth configuration
    WIREPLUMBER_CONF_DIR="/etc/wireplumber/wireplumber.conf.d"
    mkdir -p "$WIREPLUMBER_CONF_DIR"
    
    # Enable Bluetooth and configure for A2DP sink
    cat > "$WIREPLUMBER_CONF_DIR/50-bluetooth.conf" << 'EOF'
# Bluetooth configuration for Piston Audio
monitor.bluez.properties = {
    # Enable all Bluetooth features
    bluez5.enable-sbc-xq = true
    bluez5.enable-msbc = true
    bluez5.enable-hw-volume = true
    
    # Preferred codecs (highest quality first)
    bluez5.codecs = [ sbc_xq sbc aac ldac aptx aptx_hd aptx_ll aptx_ll_duplex ]
    
    # Enable A2DP sink role (receive audio)
    bluez5.roles = [ a2dp_sink ]
    
    # Auto-connect policy
    bluez5.autoswitch-profile = true
}

# Keep Bluetooth running even without active user session (headless)
wireplumber.profiles = {
    main = {
        monitor.bluez.seat-monitoring = false
    }
}
EOF

    # Create PipeWire Bluetooth config
    PIPEWIRE_CONF_DIR="/etc/pipewire/pipewire.conf.d"
    mkdir -p "$PIPEWIRE_CONF_DIR"
    
    cat > "$PIPEWIRE_CONF_DIR/50-bluetooth.conf" << 'EOF'
# Bluetooth audio configuration
context.properties = {
    # Allow Bluetooth even without seat/session
    support.dbus = true
}
EOF
    
    success "PipeWire configured for Bluetooth"
}

# Configure user session for headless operation
configure_user_session() {
    step "Configuring user session for headless operation..."
    
    # Enable autologin for the user (required for PipeWire user services)
    # This is done via raspi-config or systemd
    
    # Create systemd user directory
    USER_SYSTEMD_DIR="/home/$PISTON_USER/.config/systemd/user"
    mkdir -p "$USER_SYSTEMD_DIR"
    chown -R "$PISTON_USER:$PISTON_USER" "/home/$PISTON_USER/.config"
    
    # Enable lingering for user (keeps user services running without login)
    loginctl enable-linger "$PISTON_USER" 2>/dev/null || true
    
    # Configure autologin via getty if not already configured
    GETTY_OVERRIDE="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$GETTY_OVERRIDE"
    
    cat > "$GETTY_OVERRIDE/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $PISTON_USER --noclear %I \$TERM
EOF
    
    success "User session configured for headless operation"
}

# Create/update virtual environment and install Python dependencies
install_python_deps() {
    step "Setting up Python environment..."
    
    VENV_DIR="$INSTALL_DIR/venv"
    
    # Verify requirements.txt exists
    if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
        error "requirements.txt not found in $INSTALL_DIR"
        error "Please ensure project files are properly installed"
        exit 1
    fi
    
    # Create or update virtual environment
    if [ -d "$VENV_DIR" ]; then
        info "Updating existing virtual environment..."
    else
        info "Creating new virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    
    # Activate and install/upgrade dependencies
    source "$VENV_DIR/bin/activate"
    
    pip install --upgrade pip wheel setuptools
    pip install --upgrade -r "$INSTALL_DIR/requirements.txt"
    
    deactivate
    
    # Set ownership
    chown -R "$PISTON_USER:$PISTON_USER" "$VENV_DIR"
    
    success "Python dependencies installed/updated"
}

# Install/update systemd service
install_service() {
    step "Installing systemd service..."
    
    # Stop existing service if running
    if systemctl is-active --quiet piston-audio; then
        info "Stopping existing Piston Audio service..."
        systemctl stop piston-audio
    fi
    
    # Create systemd service file
    cat > /etc/systemd/system/piston-audio.service << EOF
[Unit]
Description=Piston Audio - Bluetooth Audio Receiver
Documentation=https://github.com/AlexProgrammerDE/piston-audio-ui
After=bluetooth.target network.target sound.target pipewire.service
Wants=bluetooth.target pipewire.service
Requires=dbus.socket

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python -m src.main --host 0.0.0.0 --port $PISTON_PORT
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket

# Hardening
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/run /tmp /run
PrivateTmp=true
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
    step "Configuring D-Bus permissions..."
    
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
    <allow send_interface="org.bluez.MediaPlayer1"/>
    <allow send_interface="org.bluez.MediaTransport1"/>
    <allow send_interface="org.freedesktop.DBus.ObjectManager"/>
    <allow send_interface="org.freedesktop.DBus.Properties"/>
  </policy>
  
  <policy context="default">
    <allow send_destination="org.piston.bluetooth"/>
  </policy>
</busconfig>
EOF

    # Reload D-Bus configuration
    systemctl reload dbus 2>/dev/null || true
    
    success "D-Bus permissions configured"
}

# Enable and start services
enable_services() {
    step "Enabling services..."
    
    # Enable core services
    systemctl enable bluetooth
    systemctl enable piston-audio
    
    # Start Bluetooth if not running
    systemctl start bluetooth
    
    # Enable PipeWire user services for the target user
    if command -v pipewire &> /dev/null; then
        # Enable PipeWire services for user
        su - "$PISTON_USER" -c "systemctl --user enable pipewire pipewire-pulse wireplumber 2>/dev/null" || true
    fi
    
    success "Services enabled"
}

# Update existing installation
update_installation() {
    step "Updating Piston Audio..."
    
    # Pull latest code if it's a git repo
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Pulling latest changes from git..."
        cd "$INSTALL_DIR"
        git fetch origin
        git reset --hard origin/main 2>/dev/null || git reset --hard origin/master 2>/dev/null || true
    fi
    
    # Update Python dependencies
    install_python_deps
    
    # Reinstall service (in case of changes)
    install_service
    
    # Restart service
    systemctl restart piston-audio
    
    success "Update complete!"
}

# Check if this is an update
is_update() {
    [ -f /etc/systemd/system/piston-audio.service ]
}

# Print final instructions
print_instructions() {
    local IP_ADDR
    IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
    
    echo ""
    echo -e "${GREEN}=============================================="
    echo "  Piston Audio Installation Complete!"
    echo -e "==============================================${NC}"
    echo ""
    echo "Installed to: $INSTALL_DIR"
    echo ""
    echo "Web Interface:"
    echo "  http://${IP_ADDR:-<your-pi-ip>}:$PISTON_PORT"
    echo ""
    echo "Service Commands:"
    echo "  Start:   sudo systemctl start piston-audio"
    echo "  Stop:    sudo systemctl stop piston-audio"
    echo "  Status:  sudo systemctl status piston-audio"
    echo "  Logs:    sudo journalctl -u piston-audio -f"
    echo ""
    echo "Your Raspberry Pi will appear as 'Piston Audio'"
    echo "in Bluetooth device lists on your phone/computer."
    echo ""
    echo -e "${YELLOW}NOTE: A reboot is recommended for all changes to take effect.${NC}"
    echo "      Run: sudo reboot"
    echo ""
}

# Main installation
main() {
    echo -e "${CYAN}"
    echo "=============================================="
    echo "  Piston Audio Installer v$VERSION"
    echo "=============================================="
    echo -e "${NC}"
    
    check_root
    detect_os
    
    if is_update; then
        info "Existing installation detected - performing update"
        setup_project_files
        update_installation
    else
        info "Fresh installation to $INSTALL_DIR"
        setup_repositories
        install_system_deps
        setup_project_files
        configure_bluetooth
        configure_pipewire
        configure_user_session
        install_python_deps
        configure_dbus
        install_service
        enable_services
    fi
    
    print_instructions
}

# Handle command line arguments
case "${1:-}" in
    --update|-u)
        check_root
        update_installation
        exit 0
        ;;
    --help|-h)
        echo "Piston Audio Installer"
        echo ""
        echo "Usage: sudo ./install.sh [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --update, -u    Update existing installation"
        echo "  --help, -h      Show this help message"
        echo ""
        exit 0
        ;;
esac

# Run main
main "$@"
