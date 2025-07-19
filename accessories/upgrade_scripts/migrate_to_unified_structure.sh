#!/bin/bash

#===============================================================================
# Ethoscope Fresh Installation Script
#===============================================================================
#
# Purpose: Perform fresh installation of ethoscope system
#          Removes any existing installations and clones fresh from repository
#
# Usage:
#   sudo ./migrate_to_unified_structure.sh           # Interactive installation
#   sudo ./migrate_to_unified_structure.sh --auto    # Automatic installation
#   sudo ./migrate_to_unified_structure.sh --check   # Check current state only
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
NC='\033[0m' # No Color

# Configuration
ETHOSCOPE_DIR="/opt/ethoscope"

# Service files for different installation types
NODE_SERVICES=(
    "ethoscope_backup"
    "ethoscope_node" 
    "ethoscope_update_node"
    "ethoscope_video_backup"
    "virtuascope"
)

DEVICE_SERVICES=(
    "ethoscope_device"
    "ethoscope_listener"
    "ethoscope_GPIO_listener"
    "ethoscope_update"
)

# Logging functions
log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root. Use sudo to run it."
        exit 1
    fi
}

# Detect installation type based on running services
detect_installation_type() {
    # Check if node services are running
    for service in "${NODE_SERVICES[@]}"; do
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            echo "node"
            return
        fi
    done
    
    # Check if device services are running
    for service in "${DEVICE_SERVICES[@]}"; do
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            echo "device" 
            return
        fi
    done
    
    echo "none"
}

# Show current state
show_status() {
    log "Ethoscope Installation Status"
    echo "=============================="
    
    local install_type
    install_type=$(detect_installation_type)
    echo "Installation type: $install_type"
    echo
    
    echo "Directory Status:"
    echo "  $ETHOSCOPE_DIR: $([ -d "$ETHOSCOPE_DIR" ] && echo "EXISTS" || echo "NOT FOUND")"
    echo
    
    echo "Service Status:"
    for service in "${NODE_SERVICES[@]}" "${DEVICE_SERVICES[@]}"; do
        local status="INACTIVE"
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            status="ACTIVE"
        fi
        echo "  ${service}.service: $status"
    done
}

# Stop services before migration
stop_services() {
    local services_to_check=()
    local install_type="$1"
    
    case "$install_type" in
        "node")
            services_to_check+=("${NODE_SERVICES[@]}")
            ;;
        "device")
            services_to_check+=("${DEVICE_SERVICES[@]}")
            ;;
    esac
    
    log "Stopping services..."
    for service in "${services_to_check[@]}"; do
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            log "Stopping ${service}.service..."
            systemctl stop "${service}.service" || warn "Failed to stop ${service}.service"
        fi
    done
    
    # Wait for services to stop
    sleep 2
}

# Fresh install node
install_node() {
    log "Performing fresh node installation..."
    
    # Remove old directories and clone fresh
    log "Removing old ethoscope directories..."
    rm -rf /opt/ethoscope*
    
    log "Cloning fresh repository..."
    git clone git://node/ethoscope.git /opt/ethoscope
    cd /opt/ethoscope && git checkout dev
    
    # Install Python packages
    log "Installing ethoscope Python package..."
    cd /opt/ethoscope/src/ethoscope/
    pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install ethoscope package"
    
    log "Installing node Python package..."
    cd /opt/ethoscope/src/node/
    pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install node package"
    
    # Remove old service files and link new ones
    log "Removing old service files..."
    rm -f /usr/lib/systemd/system/ethoscope*
    
    log "Linking new service files..."
    ln -s /opt/ethoscope/scripts/ethoscope_{node,update_node,backup,video_backup}.service virtuascope.service /usr/lib/systemd/system/
    
    # Reload systemd
    log "Reloading systemd daemon..."
    systemctl daemon-reload
}

# Fresh install device
install_device() {
    log "Performing fresh device installation..."
    
    # Remove old directories and clone fresh
    log "Removing old ethoscope directories..."
    rm -rf /opt/ethoscope*
    
    log "Cloning fresh repository..."
    git clone git://node/ethoscope.git /opt/ethoscope
    cd /opt/ethoscope && git checkout dev
    
    # Install Python package
    log "Installing ethoscope Python package..."
    cd /opt/ethoscope/src/ethoscope/
    pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install ethoscope package"
    
    # Remove old service files and link new ones
    log "Removing old service files..."
    rm -f /usr/lib/systemd/system/ethoscope*
    
    log "Linking new service files..."
    ln -s /opt/ethoscope/scripts/ethoscope_{listener,device,update,GPIO_listener}.service /usr/lib/systemd/system/
    
    # Reload systemd
    log "Reloading systemd daemon..."
    systemctl daemon-reload
    
    # Create ethoscope user
    log "Creating ethoscope user..."
    useradd -m ethoscope && passwd ethoscope
}

# Start services
finalize_installation() {
    local install_type="$1"
    
    log "Starting services..."
    
    case "$install_type" in
        "node")
            log "Starting node services..."
            systemctl restart ethoscope_node ethoscope_update_node ethoscope_backup ethoscope_video_backup
            ;;
        "device")
            log "Starting device services..."
            systemctl restart ethoscope_listener && sleep 2 && systemctl restart ethoscope_device ethoscope_update
            ;;
    esac
}

# Main installation function
perform_installation() {
    local auto_mode="$1"
    local install_type="$2"
    
    log "Starting ethoscope fresh installation..."
    
    # If install type not provided, try to detect it
    if [[ -z "$install_type" ]]; then
        install_type=$(detect_installation_type)
        
        # If still can't detect, ask user
        if [[ "$install_type" == "none" && "$auto_mode" != "--auto" ]]; then
            echo
            echo "No existing installation detected. Please specify installation type:"
            echo "1) device - Ethoscope device installation"
            echo "2) node - Ethoscope node installation"
            echo
            read -p "Enter choice (1 or 2): " -n 1 -r
            echo
            case "$REPLY" in
                1)
                    install_type="device"
                    ;;
                2)
                    install_type="node"
                    ;;
                *)
                    error "Invalid choice. Exiting."
                    exit 1
                    ;;
            esac
        elif [[ "$install_type" == "none" ]]; then
            error "Cannot detect installation type and no type specified"
            exit 1
        fi
    fi
    
    log "Installation type: $install_type"
    
    # Interactive confirmation unless in auto mode
    if [[ "$auto_mode" != "--auto" ]]; then
        echo
        warn "This will perform a FRESH installation of ethoscope system."
        warn "All existing installations will be REMOVED and replaced."
        echo
        log "The script will:"
        echo "  1. Stop running services"
        echo "  2. Remove all existing ethoscope directories"
        echo "  3. Clone fresh repository from git://node/ethoscope.git"
        echo "  4. Install Python packages"
        echo "  5. Link service files and start services"
        echo
        read -p "Do you want to continue? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Installation cancelled by user"
            exit 0
        fi
    fi
    
    # Perform installation steps
    stop_services "$install_type"
    
    case "$install_type" in
        "node")
            install_node
            ;;
        "device")
            install_device
            ;;
        *)
            error "Unknown installation type: $install_type"
            exit 1
            ;;
    esac
    
    finalize_installation "$install_type"
    
    success "Fresh installation completed successfully!"
    echo
    log "Ethoscope installed at: $ETHOSCOPE_DIR"
}

# Print usage information
usage() {
    cat << EOF
Ethoscope Fresh Installation Script

This script performs a fresh installation of the ethoscope system by removing
existing installations and cloning fresh from the repository.

Usage:
  sudo $0 [OPTIONS] [TYPE]

Options:
  --auto      Perform installation automatically without prompts
  --check     Show current installation state and exit
  --help      Show this help message

Installation Types:
  device      Install ethoscope device components
  node        Install ethoscope node components

Examples:
  sudo $0                    # Interactive installation (detects type)
  sudo $0 device            # Interactive device installation
  sudo $0 --auto node       # Automatic node installation
  sudo $0 --check           # Check current state

The script will:
1. Stop running services
2. Remove all existing ethoscope directories
3. Clone fresh repository from git://node/ethoscope.git
4. Install Python packages in development mode
5. Link service files and start services
EOF
}

# Main script execution
main() {
    case "${1:-}" in
        --check)
            show_status
            ;;
        --help|-h)
            usage
            ;;
        --auto)
            check_root
            case "${2:-}" in
                device|node)
                    perform_installation --auto "$2"
                    ;;
                "")
                    perform_installation --auto
                    ;;
                *)
                    error "Unknown installation type: $2"
                    usage
                    exit 1
                    ;;
            esac
            ;;
        device|node)
            check_root
            perform_installation "" "$1"
            ;;
        "")
            check_root
            perform_installation
            ;;
        *)
            error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"