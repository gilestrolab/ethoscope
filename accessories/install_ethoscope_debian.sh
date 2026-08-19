#!/bin/bash

#===============================================================================
# Ethoscope Device Installation Script for Debian/Raspbian
#===============================================================================
#
# Purpose: Complete installation and configuration of ethoscope software on
#          Raspberry Pi devices running Debian/Raspbian OS
#
# Target Platform: Raspberry Pi (2/3/4/5) with Debian/Raspbian
# Prerequisites: Fresh Debian/Raspbian installation with network connectivity
#
# Usage:
#   sudo ./install_ethoscope_debian.sh              # Full installation (all steps)
#   sudo ./install_ethoscope_debian.sh --from 3     # Resume from step 3
#   sudo ./install_ethoscope_debian.sh --step 5     # Run only step 5
#   sudo ./install_ethoscope_debian.sh --reset      # Reset device to ETHOSCOPE_000 defaults
#   sudo ./install_ethoscope_debian.sh --prepare-image  # Sanitise for public .img capture
#   sudo ./install_ethoscope_debian.sh --list       # List all steps
#   sudo ./install_ethoscope_debian.sh --help       # Show this help
#
# The script reboots automatically after installing system packages
# (step 1) to apply kernel/systemd updates, then resumes from step 2.
# If interrupted, re-running the script will offer to resume where it
# left off.
#
# Author: Giorgio Gilestro <giorgio@gilest.ro>
# License: GPL3
# Repository: https://github.com/gilestrolab/ethoscope
#===============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Progress tracking
PROGRESS_FILE="/etc/ethoscope/.install_progress"
SCRIPT_PATH="$(readlink -f "$0")"

# Installation steps (order matters)
STEP_NAMES=(
    "Install system packages (apt)"
    "Create ethoscope user"
    "Clone and install ethoscope software"
    "Install Arduino CLI (firmware management)"
    "Configure system identity"
    "Configure time sync (NTP)"
    "Enable system services"
    "Configure network (ethernet + WiFi)"
    "Configure WiFi"
    "Setup MariaDB database"
    "Configure MariaDB"
    "Configure Raspberry Pi hardware"
)

TOTAL_STEPS=${#STEP_NAMES[@]}

#===============================================================================
# UTILITY FUNCTIONS
#===============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}===============================================${NC}"
    echo -e "${BLUE} Ethoscope Device Installation${NC}"
    echo -e "${BLUE}===============================================${NC}"
    echo ""
}

print_step() {
    local step_num=$1
    local step_name=$2
    echo ""
    echo -e "${BOLD}[${step_num}/${TOTAL_STEPS}] ${step_name}${NC}"
    echo -e "${BLUE}-----------------------------------------------${NC}"
}

print_success() {
    echo -e "${GREEN}  ✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}  ⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}  ✗ $1${NC}"
}

print_info() {
    echo -e "  $1"
}

list_steps() {
    echo ""
    echo "Installation steps:"
    echo ""
    for i in "${!STEP_NAMES[@]}"; do
        printf "  %2d. %s\n" $((i + 1)) "${STEP_NAMES[$i]}"
    done
    echo ""
    echo "Usage:"
    echo "  sudo $0                # Run all steps"
    echo "  sudo $0 --from 3      # Resume from step 3"
    echo "  sudo $0 --step 5      # Run only step 5"
    echo ""
}

show_help() {
    echo ""
    echo "Ethoscope Device Installation Script"
    echo ""
    echo "Installs and configures ethoscope software on a Raspberry Pi."
    echo "Requires root privileges and network connectivity."
    echo ""
    echo "Options:"
    echo "  (no args)       Run full installation (all ${TOTAL_STEPS} steps)"
    echo "  --from N        Resume installation from step N"
    echo "  --step N        Run only step N"
    echo "  --reset         Reset device to ETHOSCOPE_000 defaults"
    echo "  --prepare-image Sanitise this device for public .img capture"
    echo "  --list          List all installation steps"
    echo "  --help          Show this help message"
    echo ""
    list_steps
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root. Use: sudo $0"
        exit 1
    fi
}

detect_pi_model() {
    local revision=$(grep 'Revision' /proc/cpuinfo | awk '{print $3}')

    if [[ "$revision" == "a01041" || "$revision" == "a21041" || "$revision" == "a22042" ]]; then
        PI_MODEL="pi2"
    elif [[ "$revision" == "a02082" || "$revision" == "a22082" || "$revision" == "a32082" || "$revision" == "a020d3" ]]; then
        PI_MODEL="pi3"
    elif [[ "$revision" =~ ^[bc][0-9a-f]{5}$ ]]; then
        PI_MODEL="pi4"
    elif [[ "$revision" =~ ^d[0-9a-f]{5}$ ]]; then
        PI_MODEL="pi5"
    else
        PI_MODEL="pi"
    fi

    print_info "Detected Raspberry Pi model: ${BOLD}${PI_MODEL}${NC} (revision: ${revision})"
}

determine_config_paths() {
    MYCNF=""
    BOOTCFG=""

    if [ -f "/etc/os-release" ]; then
        . /etc/os-release

        if [[ "$ID" == "debian" ]]; then
            MYCNF="/etc/mysql/mariadb.conf.d/ethoscope.cnf"
            BOOTCFG="/boot/firmware/config.txt"
        elif [[ "$ID" == "arch" ]]; then
            MYCNF="/etc/my.cnf.d/ethoscope.cnf"
            BOOTCFG="/boot/config.txt"
        fi
    fi
}

#===============================================================================
# PROGRESS TRACKING
#===============================================================================

save_progress() {
    local next_step=$1
    mkdir -p "$(dirname "$PROGRESS_FILE")"
    echo "$next_step" > "$PROGRESS_FILE"
}

clear_progress() {
    rm -f "$PROGRESS_FILE"
}

get_saved_progress() {
    if [[ -f "$PROGRESS_FILE" ]]; then
        cat "$PROGRESS_FILE"
    else
        echo "0"
    fi
}

reboot_and_resume() {
    local resume_step=$1

    save_progress "$resume_step"

    echo ""
    echo -e "${YELLOW}===============================================${NC}"
    echo -e "${YELLOW} Reboot required before continuing${NC}"
    echo -e "${YELLOW}===============================================${NC}"
    echo ""
    echo "  System packages have been installed/upgraded."
    echo "  A reboot is needed to apply kernel and systemd updates."
    echo ""
    echo "  Remaining: steps ${resume_step}-${TOTAL_STEPS} of ${TOTAL_STEPS}"
    echo ""
    echo -e "  ${BOLD}After rebooting, run:${NC}"
    echo -e "    ${BOLD}sudo $0 --from ${resume_step}${NC}"
    echo ""
    echo -e "  Or re-run without arguments — the script will offer to resume."
    echo ""

    read -p "  Reboot now? [Y/n] " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo ""
        echo -e "  When ready: ${BOLD}sudo reboot${NC}"
        echo -e "  Then run:   ${BOLD}sudo $0 --from ${resume_step}${NC}"
        echo ""
    else
        echo ""
        echo "  Rebooting in 3 seconds..."
        sleep 3
        reboot
    fi

    exit 0
}

#===============================================================================
# PWM LIGHT BACKEND: pigpio from source (Trixie and later)
#===============================================================================
#
# Why this exists — the lesson, crystallised:
#
#  * The light daemon dims the LED with PWM. Two backends can do it: pigpio and
#    lgpio/gpiozero. They are NOT interchangeable on the legacy boards, whose
#    LED sits on GPIO17 (a non-hardware-PWM pin):
#      - pigpio clocks PWM off the DMA engine, so it dims *any* GPIO cleanly and
#        is immune to CPU load. A tracking ethoscope runs its Pi at saturation,
#        so this matters.
#      - lgpio times PWM on the CPU, so on a saturated Pi it visibly flickers on
#        non-hardware-PWM pins. light_daemon.py therefore refuses lgpio on GPIO17
#        and drops to steady on/off. lgpio only gives clean PWM on the hardware
#        PWM pins 12/13/18/19.
#    So on a GPIO17 board, dimming REQUIRES pigpio. gpiozero/lgpio (installed
#    unconditionally in step 1) is only the fallback for hardware-PWM-pin boards.
#
#  * Debian Trixie — and Raspberry Pi OS from Trixie on — ships NO pigpio apt
#    package (upstream is stepping away from it; it cannot run on the Pi 5). So
#    the apt check in step 1 fails and we build the last tagged release, v79,
#    from source. Verified on Pi 3B / Trixie / kernel 6.x / Python 3.13.
#    Refs: https://forums.raspberrypi.com/viewtopic.php?t=392438
#          https://github.com/joan2937/pigpio/issues/632
#
#  * Gotchas found the hard way, now handled below:
#      - Python 3.12 removed the stdlib `distutils` that pigpio's setup.py
#        imports. Without python3-setuptools + python3-full (which restore the
#        setuptools distutils shim) `make install` dies with
#        "ModuleNotFoundError: No module named 'distutils'".
#      - `make install` installs under /usr/local (pigpiod -> /usr/local/bin),
#        NOT /usr/bin like the old apt package, and ships NO systemd unit. We
#        write the unit ourselves; step 7 resolves the binary path dynamically
#        so the apt (/usr/bin) and source (/usr/local/bin) layouts both work.
#      - pigpiod's default socket port 8888 collides with ethoscope_update on an
#        ethoscope. Step 7 starts it on 8889 to match PIGPIO_PORT in
#        light_daemon.py; `-l` keeps the socket on localhost only.
#
install_pigpio_from_source() {
    print_info "Building pigpio v79 from source (no package on this release)..."

    # setuptools/full provide the distutils shim pigpio's setup.py needs on 3.12+
    apt-get install -y python3-setuptools python3-full

    local src="/tmp/pigpio-79"
    rm -rf "$src" /tmp/pigpio-v79.tar.gz
    if ! wget -qO /tmp/pigpio-v79.tar.gz \
            https://github.com/joan2937/pigpio/archive/refs/tags/v79.tar.gz; then
        print_warning "Could not download pigpio source — light control stays on/off"
        return 1
    fi
    tar zxf /tmp/pigpio-v79.tar.gz -C /tmp

    if make -C "$src" -j"$(nproc)" && make -C "$src" install; then
        ldconfig
        print_success "Built and installed pigpio v79 (pigpiod -> $(command -v pigpiod))"
    else
        print_warning "pigpio build failed — light control falls back to lgpio/on-off"
        return 1
    fi

    # Guarantee the Python client module even if the Makefile's deprecated
    # `setup.py install` step was skipped or failed.
    python3 -c "import pigpio" 2>/dev/null || \
        pip3 install pigpio --break-system-packages --ignore-installed 2>/dev/null || true

    # make install ships no unit, so provide a base one. Deliberately minimal:
    # step 7 owns the port/host flags via a drop-in, keeping a single source of
    # truth for the port across the apt and from-source layouts. pigpiod forks
    # by default, hence Type=forking.
    local pigpiod_bin
    pigpiod_bin="$(command -v pigpiod || echo /usr/local/bin/pigpiod)"
    cat > /etc/systemd/system/pigpiod.service <<PIGPIOD_UNIT
[Unit]
Description=pigpio daemon (built from source; DMA PWM backend for light control)
After=network.target

[Service]
Type=forking
ExecStart=${pigpiod_bin}
ExecStop=/bin/systemctl kill pigpiod
RestartSec=5
Restart=always

[Install]
WantedBy=multi-user.target
PIGPIOD_UNIT
    systemctl daemon-reload 2>/dev/null || true
    print_success "Installed pigpiod.service (port applied by step 7)"
}

#===============================================================================
# STEP 1: PACKAGE INSTALLATION
#===============================================================================

step_install_apt_packages() {
    print_info "Updating package lists..."
    apt-get update

    print_info "Upgrading existing packages..."
    apt-get upgrade -y

    print_info "Installing system packages..."
    apt-get install -y \
        mariadb-server \
        mariadb-client \
        sqlite3 \
        systemd-resolved \
        build-essential \
        python3-dev \
        libcap-dev \
        pkg-config \
        python3-gpiozero \
        python3-lgpio \
        git wget curl

    # PWM backend for the light daemon. pigpio is the only backend that dims the
    # LED on GPIO17 without CPU-load flicker (see install_pigpio_from_source
    # above for the full rationale). Where an apt package still exists (Bookworm
    # and earlier) use it; from Trixie on there is none, so build v79 from
    # source. gpiozero/lgpio, installed unconditionally above, is the fallback.
    print_info "Installing PWM backend for light control..."
    if apt-cache show pigpio >/dev/null 2>&1; then
        apt-get install -y pigpio python3-pigpio && \
            print_success "Installed pigpio (PWM backend, apt)"
    else
        install_pigpio_from_source || \
            print_warning "pigpio unavailable — light falls back to lgpio/on-off"
    fi

    # NTP: ntp was removed in Trixie, replaced by ntpsec
    print_info "Installing NTP service..."
    if apt-cache show ntp >/dev/null 2>&1 && apt-get install -y ntp 2>/dev/null; then
        print_success "Installed ntp"
    elif apt-get install -y ntpsec 2>/dev/null; then
        print_success "Installed ntpsec (ntp replacement)"
    else
        print_warning "No NTP package found — time sync will rely on systemd-timesyncd"
    fi

    print_info "Restarting network services..."
    systemctl restart systemd-networkd systemd-resolved || true

    print_info "Installing Python packages..."
    apt-get install -y \
        python3-pip \
        python3-venv \
        python3-setuptools \
        python3-picamera2 \
        python3-usb \
        python3-protobuf

    print_success "All system packages installed"
}

#===============================================================================
# STEP 2: USER MANAGEMENT
#===============================================================================

step_setup_ethoscope_user() {
    if id "ethoscope" &>/dev/null; then
        print_info "User 'ethoscope' already exists"
    else
        print_info "Creating ethoscope user account..."
        useradd -m ethoscope
    fi
    echo -e "ethoscope\nethoscope" | passwd ethoscope 2>/dev/null
    usermod -a -G root ethoscope
    print_success "Ethoscope user configured (password: ethoscope)"
}

#===============================================================================
# STEP 3: SOFTWARE INSTALLATION
#===============================================================================

step_install_ethoscope_software() {
    # Create system-wide pip config
    cat > /etc/pip.conf << 'EOF'
[global]
break-system-packages = true
EOF

    if [[ -d "/opt/ethoscope" ]]; then
        print_info "Removing existing /opt/ethoscope for clean install..."
        rm -rf /opt/ethoscope
    fi

    print_info "Cloning ethoscope repository..."
    git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope

    print_info "Configuring git repository..."
    cd /opt/ethoscope/
    git checkout dev
    git remote set-url origin git://node.local/ethoscope.git

    # Secondary remote pointing straight at GitHub. `origin` stays on the local
    # node mirror (git://node.local) for routine updates, but keeping a `github`
    # remote lets a device fetch upstream directly when the node is unreachable
    # or the mirror is stale (e.g. git fetch github && git checkout github/dev).
    git remote add github "$GITHUB_REPO" 2>/dev/null || \
        git remote set-url github "$GITHUB_REPO"

    # Use --system instead of --global to avoid requiring $HOME
    git config --system --add safe.directory /opt/ethoscope

    print_info "Installing ethoscope Python package..."
    cd /opt/ethoscope/src/ethoscope
    pip3 install -e . --break-system-packages --ignore-installed

    print_info "Configuring picamera2..."
    pip3 uninstall -y picamera 2>/dev/null || true
    pip3 install picamera2 --break-system-packages 2>/dev/null || true

    print_info "Installing systemd service files..."
    rm -rf /usr/lib/systemd/system/{ethoscope_device,ethoscope_listener,ethoscope_GPIO_listener,ethoscope_light,ethoscope_update}.service 2>/dev/null
    ln -sf /opt/ethoscope/services/{ethoscope_device,ethoscope_listener,ethoscope_GPIO_listener,ethoscope_light,ethoscope_update}.service /usr/lib/systemd/system/

    print_info "Creating ethoclient command line tool..."
    echo $'#!/bin/env bash\npython /opt/ethoscope/src/ethoscope/scripts/ethoclient.py $@' > /usr/bin/ethoclient
    chmod +x /usr/bin/ethoclient

    print_info "Creating ethoscope-light CLI wrapper..."
    echo $'#!/bin/env bash\npython /opt/ethoscope/src/ethoscope/ethoscope/hardware/interfaces/light_cli.py "$@"' > /usr/bin/ethoscope-light
    chmod +x /usr/bin/ethoscope-light

    print_success "Ethoscope software installed to /opt/ethoscope"
}

#===============================================================================
# STEP 4: ARDUINO CLI INSTALLATION
#===============================================================================

step_install_arduino_cli() {
    ARDUINO_CLI_VERSION="1.4.1"
    ARCH=$(dpkg --print-architecture)  # armhf or arm64

    print_info "Downloading arduino-cli v${ARDUINO_CLI_VERSION} for ${ARCH}..."
    wget -q "https://github.com/arduino/arduino-cli/releases/download/v${ARDUINO_CLI_VERSION}/arduino-cli_${ARDUINO_CLI_VERSION}-1_${ARCH}.deb" \
        -O /tmp/arduino-cli.deb

    print_info "Installing arduino-cli package..."
    dpkg -i /tmp/arduino-cli.deb
    rm -f /tmp/arduino-cli.deb

    print_info "Installing Arduino AVR core (this may take a few minutes)..."
    arduino-cli core update-index
    arduino-cli core install arduino:avr

    print_success "Arduino CLI installed ($(arduino-cli version 2>/dev/null | head -1))"
}

#===============================================================================
# STEP 5: SYSTEM IDENTITY
#===============================================================================

step_configure_system_identity() {
    print_info "Setting default hostname to ETHOSCOPE000..."
    echo "ETHOSCOPE_000" > /etc/machine-name
    # Use raspi-config to set hostname
    # This also updates /etc/hosts and notifies systemd
    raspi-config nonint do_hostname "ETHOSCOPE000"
    # Prevent cloud-init from reverting hostname and /etc/hosts on reboot
    if [ -f /etc/cloud/cloud.cfg ]; then
        sed -i 's/preserve_hostname: false/preserve_hostname: true/' /etc/cloud/cloud.cfg
        sed -i 's/manage_etc_hosts: true/manage_etc_hosts: false/' /etc/cloud/cloud.cfg
        # Ensure settings exist even if not present in the original file
        grep -q 'preserve_hostname' /etc/cloud/cloud.cfg || echo 'preserve_hostname: true' >> /etc/cloud/cloud.cfg
        grep -q 'manage_etc_hosts' /etc/cloud/cloud.cfg || echo 'manage_etc_hosts: false' >> /etc/cloud/cloud.cfg
    fi

    print_info "Configuring login banner..."
    echo 'Ethoscope Linux \r  (\n) (\l)' > /etc/issue
    echo 'Ethernet IP: \4{eth0}' >> /etc/issue
    echo 'WIFI IP: \4{wlan0}' >> /etc/issue
    echo 'Time on Device: \d \t' >> /etc/issue

    print_info "Limiting journal log to 250MB..."
    echo 'SystemMaxUse=250MB' >> /etc/systemd/journald.conf

    print_info "Generating en_GB.UTF-8 locale..."
    echo "en_GB.UTF-8 UTF-8" >> /etc/locale.gen
    locale-gen

    echo $(date +%Y%m%d)_ethoscope000_${PI_MODEL}.img > /etc/sdimagename

    print_success "System identity configured as ETHOSCOPE_000"
}

#===============================================================================
# STEP 6: TIME SYNC
#===============================================================================

step_configure_time_sync() {
    print_info "Configuring NTP to sync with node server..."

    local ntp_config="server node
server 127.127.1.0
fudge 127.127.1.0 stratum 10
restrict default kod limited nomodify nopeer noquery notrap
restrict 127.0.0.1
restrict ::1
driftfile /var/lib/ntp/ntp.drift"

    # ntpsec uses /etc/ntpsec/ntp.conf, classic ntp uses /etc/ntp.conf
    if [[ -d "/etc/ntpsec" ]]; then
        echo "$ntp_config" > /etc/ntpsec/ntp.conf
        print_success "NTP configured (ntpsec) to use node as time source"
    else
        echo "$ntp_config" > /etc/ntp.conf
        print_success "NTP configured to use node as time source"
    fi
}

#===============================================================================
# STEP 7: SYSTEM SERVICES
#===============================================================================

step_enable_system_services() {
    print_info "Enabling ethoscope services..."
    systemctl enable ethoscope_device.service ethoscope_listener.service \
        ethoscope_update.service ethoscope_GPIO_listener.service \
        ethoscope_light.service

    # pigpiod drives the PWM light backend where it exists. From Trixie onwards
    # it is absent and the daemon uses gpiozero/lgpio instead, which needs no
    # service, so its absence is expected rather than a problem.
    if systemctl list-unit-files 2>/dev/null | grep -q "^pigpiod\.service"; then
        # pigpiod defaults to port 8888, which on an ethoscope belongs to
        # ethoscope_update.service. It cannot bind there, and a client using the
        # default port connects to the *update server*, is told the connection
        # succeeded, and then sends GPIO commands to an HTTP server - light
        # silently dead. Pin both sides to 8889 (see PIGPIO_PORT in light_daemon).
        # This drop-in is the single place the port is defined, for both the apt
        # unit and the from-source one. `-l` keeps the socket on localhost only.
        # Resolve the binary dynamically: apt installs /usr/bin/pigpiod, a source
        # build installs /usr/local/bin/pigpiod.
        local pigpiod_bin
        pigpiod_bin="$(command -v pigpiod || echo /usr/bin/pigpiod)"
        mkdir -p /etc/systemd/system/pigpiod.service.d
        cat > /etc/systemd/system/pigpiod.service.d/port.conf <<PIGPIOD_PORT
[Service]
ExecStart=
ExecStart=${pigpiod_bin} -l -p 8889
PIGPIOD_PORT
        systemctl daemon-reload 2>/dev/null || true
        systemctl enable pigpiod.service 2>/dev/null && \
            print_success "Enabled pigpiod.service on port 8889 (PWM backend for fades)"
    else
        print_info "pigpiod.service not present — light daemon will use gpiozero/lgpio PWM"
        print_info "  (GPIO17 boards then get steady on/off only; dimming needs"
        print_info "   pigpio, or the LED on a hardware-PWM GPIO: 12, 13, 18, 19)"
    fi

    # NTP service
    print_info "Enabling NTP service..."
    local ntp_enabled=false
    for service in "ntpsec.service" "ntp.service" "ntpd.service" "systemd-timesyncd.service" "chronyd.service"; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${service}"; then
            systemctl enable "$service" 2>/dev/null && ntp_enabled=true && break
        fi
    done
    if $ntp_enabled; then
        print_success "NTP service enabled"
    else
        print_warning "No NTP service found — time sync may need manual setup"
    fi

    # MariaDB service
    print_info "Enabling database service..."
    for service in "mariadb.service" "mysql.service" "mysqld.service"; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${service}"; then
            systemctl enable "$service" 2>/dev/null
            print_success "Enabled $service"
            break
        fi
    done

    # SSH service
    for service in "ssh.service" "sshd.service"; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${service}"; then
            systemctl enable "$service" 2>/dev/null
            print_success "Enabled $service"
            break
        fi
    done

    # Avahi
    if systemctl list-unit-files 2>/dev/null | grep -q "^avahi-daemon\.service"; then
        systemctl enable avahi-daemon.service 2>/dev/null
        print_success "Enabled avahi-daemon.service"
    fi
}

#===============================================================================
# STEP 8: NETWORK CONFIGURATION
#===============================================================================

step_configure_network() {
    print_info "Disabling conflicting network managers..."
    systemctl disable NetworkManager ModemManager dhcpcd 2>/dev/null || true
    systemctl stop NetworkManager ModemManager dhcpcd 2>/dev/null || true

    print_info "Configuring wired network (eth0)..."
    cat > /etc/systemd/network/20-wired.network << 'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes
LinkLocalAddressing=yes

[DHCPv4]
RouteMetric=10
UseDNS=yes
EOF

    print_info "Configuring wireless network (wlan0)..."
    cat > /etc/systemd/network/25-wireless.network << 'EOF'
[Match]
Name=wlan0

[Network]
DHCP=yes
LinkLocalAddressing=yes

[DHCPv4]
RouteMetric=20
UseDNS=yes
EOF

    systemctl enable systemd-networkd systemd-resolved
    systemctl disable systemd-networkd-wait-online 2>/dev/null || true

    ip link set eth0 up 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true

    mkdir -p /etc/systemd/resolved.conf.d
    cat > /etc/systemd/resolved.conf.d/ethoscope.conf << 'EOF'
[Resolve]
DNS=8.8.8.8 1.1.1.1
FallbackDNS=8.8.4.4 1.0.0.1
EOF

    print_success "Network configured"
}

#===============================================================================
# STEP 9: WIFI CONFIGURATION
#===============================================================================

step_configure_wifi() {
    print_info "Setting WiFi country to GB..."
    if command -v raspi-config >/dev/null 2>&1; then
        raspi-config nonint do_wifi_country GB
    else
        if [[ ! -f /etc/wpa_supplicant/wpa_supplicant.conf ]] || ! grep -q "country=" /etc/wpa_supplicant/wpa_supplicant.conf; then
            echo "country=GB" >> /etc/wpa_supplicant/wpa_supplicant.conf
        fi
    fi

    if command -v rfkill >/dev/null 2>&1; then
        print_info "Unblocking WiFi..."
        rfkill unblock wifi
        rfkill unblock all
    fi

    print_info "Configuring default WiFi (ETHOSCOPE_WIFI)..."
    wpa_passphrase ETHOSCOPE_WIFI ETHOSCOPE_1234 > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
    systemctl enable wpa_supplicant
    systemctl enable wpa_supplicant@wlan0.service

    print_success "WiFi configured (SSID: ETHOSCOPE_WIFI)"
}

#===============================================================================
# STEP 10: MARIADB SETUP
#===============================================================================

step_setup_mariadb() {
    if [ ! -d "/var/lib/mysql/mysql" ]; then
        print_info "Initializing MariaDB data directory..."
        mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
    fi

    chown -R mysql:mysql /var/lib/mysql

    print_info "Starting MariaDB..."
    systemctl start mysqld.service || systemctl start mariadb.service || true

    print_info "Waiting for MariaDB to be ready..."
    for i in {1..30}; do
        if mysqladmin ping >/dev/null 2>&1; then
            break
        fi
        if [ $i -eq 30 ]; then
            print_error "MariaDB failed to start within 30 seconds"
            exit 1
        fi
        sleep 1
    done

    print_info "Creating database users..."
    mysql -u root <<EOF
CREATE USER IF NOT EXISTS 'ethoscope'@'localhost' IDENTIFIED BY 'ethoscope';
CREATE USER IF NOT EXISTS 'node'@'%' IDENTIFIED BY 'node';
GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'localhost' WITH GRANT OPTION;
GRANT SELECT ON *.* TO 'node'@'%';
FLUSH PRIVILEGES;
EOF

    print_success "MariaDB configured (user: ethoscope, password: ethoscope)"
}

#===============================================================================
# STEP 11: MARIADB CONFIGURATION
#===============================================================================

step_configure_mariadb() {
    local buffer_pool_size="64M"
    local log_file_size="16M"
    local key_buffer_size="16M"
    local max_connections="50"

    case "$PI_MODEL" in
        pi2)  buffer_pool_size="32M";  log_file_size="8M";  key_buffer_size="8M";  max_connections="25" ;;
        pi3)  buffer_pool_size="64M";  log_file_size="16M"; key_buffer_size="16M"; max_connections="40" ;;
        pi4)  buffer_pool_size="128M"; log_file_size="32M"; key_buffer_size="32M"; max_connections="75" ;;
        pi5)  buffer_pool_size="256M"; log_file_size="64M"; key_buffer_size="64M"; max_connections="100" ;;
    esac

    if [ -n "$MYCNF" ]; then
        mkdir -p "$(dirname "$MYCNF")"
        print_info "Writing MariaDB config to $MYCNF (tuned for $PI_MODEL)..."
        cat > "$MYCNF" <<EOF
[server]
log-bin          = mysql-bin
binlog_format    = mixed
expire_logs_days = 10
max_binlog_size  = 100M
bind-address     = 0.0.0.0
innodb_buffer_pool_size = $buffer_pool_size
innodb_log_file_size = $log_file_size
key_buffer_size = $key_buffer_size
max_connections = $max_connections
innodb_flush_log_at_trx_commit = 2
sync_binlog = 0
EOF
        print_success "MariaDB tuned for $PI_MODEL"
    else
        print_warning "Could not determine MariaDB config location"
    fi
}

#===============================================================================
# STEP 12: HARDWARE CONFIGURATION
#===============================================================================

step_configure_raspberry_pi_hardware() {
    print_info "Configuring hardware for $PI_MODEL..."

    echo 'dtoverlay=disable-bt' >> "$BOOTCFG"
    echo 'hdmi_force_hotplug=1' >> "$BOOTCFG"
    echo 'dtparam=i2c_arm=on' >> "$BOOTCFG"
    echo 'i2c-dev' >> /etc/modules-load.d/raspberrypi.conf
    echo 'disable_camera_led=1' >> "$BOOTCFG"

    case "$PI_MODEL" in
        pi2|pi3)
            print_info "Configuring legacy camera (Pi 2/3)..."
            echo 'start_file=start_x.elf' >> "$BOOTCFG"
            echo 'fixup_file=fixup_x.dat' >> "$BOOTCFG"
            echo 'gpu_mem=256' >> "$BOOTCFG"
            echo 'cma_lwm=' >> "$BOOTCFG"
            echo 'cma_hwm=' >> "$BOOTCFG"
            echo 'cma_offline_start=' >> "$BOOTCFG"
            echo 'awb_auto_is_greyworld=1' >> "$BOOTCFG"
            echo 'bcm2835-v4l2' > /etc/modules-load.d/picamera.conf
            ;;
        pi4|pi5)
            print_info "Configuring camera for Pi ${PI_MODEL#pi}..."
            echo 'dtoverlay=vc4-kms-v3d' >> "$BOOTCFG"
            echo 'gpu_mem=256' >> "$BOOTCFG"
            echo 'dtoverlay=imx219' >> "$BOOTCFG"
            ;;
        *)
            print_info "Using basic camera configuration..."
            echo 'gpu_mem=128' >> "$BOOTCFG"
            echo 'dtoverlay=imx219' >> "$BOOTCFG"
            ;;
    esac

    echo 'camera_auto_detect=1' >> "$BOOTCFG"
    echo 'dtparam=camera=on' >> "$BOOTCFG"

    print_success "Hardware configured for $PI_MODEL"
}

#===============================================================================
# RESET TO ETHOSCOPE_000
#===============================================================================
# Resets a configured ethoscope back to factory defaults (ETHOSCOPE_000).
# Reuses installation steps where possible, adds update & cleanup utilities.

GITHUB_REPO="https://github.com/gilestrolab/ethoscope.git"
LOCAL_REPO="git://node.local/ethoscope.git"
ETHOSCOPE_PATH="/opt/ethoscope"

reset_update_repository() {
    print_info "Updating repository from GitHub..."

    if [[ ! -d "$ETHOSCOPE_PATH/.git" ]]; then
        print_error "No git repository at $ETHOSCOPE_PATH"
        print_info "Use full installation instead: $0"
        exit 1
    fi

    cd "$ETHOSCOPE_PATH" || exit 1

    # Ensure safe.directory is set for root operations
    git config --system --add safe.directory "$ETHOSCOPE_PATH" 2>/dev/null || true

    # Stash any local changes to avoid conflicts
    if git status --porcelain | grep -q .; then
        print_warning "Local changes detected. Stashing them..."
        git stash
    fi

    git remote set-url origin "$GITHUB_REPO"
    git fetch origin
    git checkout dev
    git pull origin dev
    git remote set-url origin "$LOCAL_REPO"

    print_success "Repository updated"
}

reset_set_system_date() {
    print_info "Setting system date from internet..."

    if ! command -v wget &> /dev/null; then
        print_warning "wget not found — skipping date sync"
        return
    fi

    # Use a subshell to isolate pipeline failures from set -e
    local date_string
    date_string=$(wget --method=HEAD -qSO- --max-redirect=0 --timeout=10 google.com 2>&1 | grep "Date:" | cut -d' ' -f5-10) || true

    if [[ -n "$date_string" ]]; then
        date -s "$date_string"
        print_success "System date updated"
    else
        print_warning "Could not retrieve date from internet"
    fi
}

reset_set_timezone() {
    print_info "Setting timezone to UTC..."
    if command -v timedatectl &> /dev/null; then
        timedatectl set-timezone UTC
        print_success "Timezone set to UTC"
    else
        print_warning "timedatectl not found — skipping timezone"
    fi
}

reset_clean_package_cache() {
    print_info "Cleaning package cache..."
    if command -v apt-get &> /dev/null; then
        apt-get clean
        print_success "APT cache cleaned"
    elif command -v pacman &> /dev/null; then
        pacman -Scc --noconfirm
        print_success "Pacman cache cleaned"
    else
        print_warning "No recognized package manager found"
    fi
}

do_reset() {
    check_root
    print_header
    detect_pi_model
    determine_config_paths

    echo -e "  ${YELLOW}This will reset the device to ETHOSCOPE_000 defaults.${NC}"
    echo ""

    reset_update_repository
    reset_set_system_date
    step_configure_system_identity    # Reuse install step 5
    reset_set_timezone
    step_configure_network            # Reuse install step 8
    reset_clean_package_cache

    echo ""
    echo -e "${GREEN}===============================================${NC}"
    echo -e "${GREEN} Device reset to ETHOSCOPE_000 complete${NC}"
    echo -e "${GREEN}===============================================${NC}"
    echo ""
    echo -e "  ${BOLD}Please reboot now: sudo reboot${NC}"
    echo ""
}

#===============================================================================
# PREPARE FOR IMAGING
#===============================================================================
# Sanitise a configured card so it can be captured as a distributable .img.
# Everything here was learned making the first Trixie public image (2026-08):
#
#  * SSH host keys are per-device. Baked into an image, every flashed device
#    would share them — a security hole and an endless stream of host-key
#    mismatch warnings. Delete them; sshd-keygen.service and
#    regenerate_ssh_host_keys.service (both enabled on the RPi/Trixie image)
#    mint fresh, unique keys on first boot.
#
#  * DO **NOT** blank /etc/machine-id. systemd reads an empty machine-id as
#    ConditionFirstBoot=yes, which can fire first-boot units that block on a
#    console the headless device doesn't have — i.e. a hung first boot. A shared
#    base machine-id is harmless here: the ethoscope regenerates its own when it
#    is renamed from ETHOSCOPE_000 to a real device number. So we only guarantee
#    a valid, NON-EMPTY machine-id and otherwise leave it alone.
#
#  * Drop install logs, shell history, stale ssh known_hosts, package/pip caches
#    and the journal so the image is clean and as small as possible before
#    ethoscope-image.sh --shrink runs on the captured file.
#
# After this: power off cleanly (sudo poweroff — never pull power), capture the
# card (dd / rpi-imager), then finish on the .img with:
#     sudo ./ethoscope-image.sh --rename --shrink path/to/image.img
prepare_image() {
    check_root
    print_header
    print_info "Preparing this device for image capture..."

    print_info "Removing install artefacts, shell history and known_hosts..."
    rm -f /home/ethoscope/install*.log /home/ethoscope/install_ethoscope_debian.sh
    rm -f /home/ethoscope/.bash_history /root/.bash_history
    rm -f /home/ethoscope/.ssh/known_hosts /root/.ssh/known_hosts
    clear_progress

    print_info "Deleting SSH host keys (regenerated uniquely on first boot)..."
    rm -f /etc/ssh/ssh_host_*

    # Guarantee a valid machine-id, but never an empty one (see header note).
    if [[ ! -s /etc/machine-id ]]; then
        print_warning "machine-id was empty — regenerating (an empty one can hang first boot)"
        systemd-machine-id-setup
    fi
    print_info "Leaving machine-id intact: $(cat /etc/machine-id)"

    reset_clean_package_cache
    rm -rf /root/.cache/pip /home/ethoscope/.cache/pip

    print_info "Vacuuming the systemd journal..."
    journalctl --rotate >/dev/null 2>&1 || true
    journalctl --vacuum-time=1s >/dev/null 2>&1 || true

    echo ""
    echo -e "${GREEN}===============================================${NC}"
    echo -e "${GREEN} Device ready for image capture${NC}"
    echo -e "${GREEN}===============================================${NC}"
    echo ""
    echo -e "  Next:"
    echo -e "    1. ${BOLD}sudo poweroff${NC}   (clean shutdown — never pull power)"
    echo -e "    2. Capture the card, e.g. ${BOLD}dd if=/dev/mmcblkX of=ethoscope.img bs=4M${NC}"
    echo -e "    3. ${BOLD}sudo ./ethoscope-image.sh --rename --shrink ethoscope.img${NC}"
    echo ""
}

#===============================================================================
# STEP DISPATCHER
#===============================================================================

# Steps that require a reboot AFTER completion before continuing.
# The value is the next step to resume from.
REBOOT_AFTER_STEP=1  # Reboot after apt upgrade (kernel/systemd updates)

# Map step numbers to functions
run_step() {
    local step_num=$1
    print_step "$step_num" "${STEP_NAMES[$((step_num - 1))]}"

    case $step_num in
        1)  step_install_apt_packages ;;
        2)  step_setup_ethoscope_user ;;
        3)  step_install_ethoscope_software ;;
        4)  step_install_arduino_cli ;;
        5)  step_configure_system_identity ;;
        6)  step_configure_time_sync ;;
        7)  step_enable_system_services ;;
        8)  step_configure_network ;;
        9)  step_configure_wifi ;;
        10) step_setup_mariadb ;;
        11) step_configure_mariadb ;;
        12) step_configure_raspberry_pi_hardware ;;
        *)  print_error "Unknown step: $step_num"; exit 1 ;;
    esac

    print_success "Step ${step_num} complete"
}

#===============================================================================
# MAIN EXECUTION
#===============================================================================

main() {
    local start_step=1
    local end_step=$TOTAL_STEPS
    local single_step=0

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                show_help
                exit 0
                ;;
            --list|-l)
                list_steps
                exit 0
                ;;
            --from)
                start_step="$2"
                if [[ -z "$start_step" ]] || [[ "$start_step" -lt 1 ]] || [[ "$start_step" -gt $TOTAL_STEPS ]]; then
                    print_error "Invalid step number. Use --list to see available steps."
                    exit 1
                fi
                shift 2
                ;;
            --step)
                single_step="$2"
                if [[ -z "$single_step" ]] || [[ "$single_step" -lt 1 ]] || [[ "$single_step" -gt $TOTAL_STEPS ]]; then
                    print_error "Invalid step number. Use --list to see available steps."
                    exit 1
                fi
                start_step=$single_step
                end_step=$single_step
                shift 2
                ;;
            --reset)
                do_reset
                exit 0
                ;;
            --prepare-image|--prepare)
                prepare_image
                exit 0
                ;;
            --apt-install)
                # Legacy flag — equivalent to --step 1
                print_warning "The --apt-install flag is deprecated. Use --step 1 instead."
                single_step=1
                start_step=1
                end_step=1
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    check_root
    print_header
    detect_pi_model
    determine_config_paths

    # Check for saved progress from a previous interrupted run
    local saved=$(get_saved_progress)
    if [[ $saved -gt 0 ]] && [[ $start_step -eq 1 ]] && [[ $single_step -eq 0 ]]; then
        echo ""
        echo -e "  ${YELLOW}Previous installation was interrupted at step ${saved}.${NC}"
        read -p "  Resume from step ${saved}? [Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            start_step=$saved
        else
            clear_progress
        fi
    fi

    if [[ $single_step -gt 0 ]]; then
        print_info "Running step ${single_step} only"
    elif [[ $start_step -gt 1 ]]; then
        print_info "Resuming from step ${start_step} of ${TOTAL_STEPS}"
    else
        print_info "Running full installation (${TOTAL_STEPS} steps)"
    fi

    echo ""

    # Run the steps
    for ((step = start_step; step <= end_step; step++)); do
        run_step $step

        # Reboot gate: if this step requires a reboot and we have more steps to go
        if [[ $step -eq $REBOOT_AFTER_STEP ]] && [[ $step -lt $end_step ]] && [[ $single_step -eq 0 ]]; then
            reboot_and_resume $((step + 1))
        fi
    done

    # Clean up progress tracking
    clear_progress

    # Show completion message only for full or tail-end installs
    if [[ $end_step -eq $TOTAL_STEPS ]]; then
        echo ""
        echo -e "${GREEN}===============================================${NC}"
        echo -e "${GREEN} Ethoscope installation completed!${NC}"
        echo -e "${GREEN}===============================================${NC}"
        echo ""
        echo "  Next steps:"
        echo "  1. Reboot: sudo reboot"
        echo "  2. After reboot, device will be accessible as ETHOSCOPE_000"
        echo "  3. Change the device ID from 000 to a unique number"
        echo "  4. Connect to the ethoscope network node"
        echo ""
        echo -e "  ${BOLD}Please reboot now: sudo reboot${NC}"
        echo ""
    fi
}

main "$@"
