#!/bin/bash

#===============================================================================
# Ethoscope Repository Structure Migration Script
#===============================================================================
#
# Purpose: Migrate from old separate directory structure to new unified structure
#          Old: /opt/ethoscope-device and /opt/ethoscope-node 
#          New: /opt/ethoscope (unified)
#
# This script handles the system-level changes needed after pulling the new
# dev branch. Git handles the file reorganization.
#
# Usage:
#   sudo ./migrate_to_unified_structure.sh           # Interactive migration
#   sudo ./migrate_to_unified_structure.sh --auto    # Automatic migration
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
OLD_DEVICE_DIR="/opt/ethoscope-device"
OLD_NODE_DIR="/opt/ethoscope-node"
NEW_UNIFIED_DIR="/opt/ethoscope"

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

# Detect installation type and current state
detect_installation_type() {
    if [[ -d "$OLD_NODE_DIR" ]]; then
        echo "node"
    elif [[ -d "$OLD_DEVICE_DIR" ]]; then
        echo "device"
    else
        echo "none"
    fi
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
    echo "  $OLD_DEVICE_DIR: $([ -d "$OLD_DEVICE_DIR" ] && echo "EXISTS" || echo "NOT FOUND")"
    echo "  $OLD_NODE_DIR: $([ -d "$OLD_NODE_DIR" ] && echo "EXISTS" || echo "NOT FOUND")"
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

# Migrate node installation
migrate_node() {
    log "Migrating node installation..."
    
    # Move directory
    log "Moving $OLD_NODE_DIR to $NEW_UNIFIED_DIR..."
    mv "$OLD_NODE_DIR" "$NEW_UNIFIED_DIR"
    
    # Remove old service files
    log "Removing old service files..."
    for service in "${NODE_SERVICES[@]}"; do
        rm -f "/usr/lib/systemd/system/${service}.service"
        rm -f "/etc/systemd/system/${service}.service"
    done
    
    # Link new service files
    log "Linking new service files..."
    for service in "${NODE_SERVICES[@]}"; do
        if [[ -f "$NEW_UNIFIED_DIR/scripts/${service}.service" ]]; then
            ln -sf "$NEW_UNIFIED_DIR/scripts/${service}.service" "/usr/lib/systemd/system/"
            log "Linked ${service}.service"
        else
            warn "Service file not found: $NEW_UNIFIED_DIR/scripts/${service}.service"
        fi
    done
    
    # Install Python packages
    log "Installing node Python package..."
    if [[ -d "$NEW_UNIFIED_DIR/src/node" ]]; then
        cd "$NEW_UNIFIED_DIR/src/node"
        pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install node package"
    fi
    
    log "Installing ethoscope Python package..."
    if [[ -d "$NEW_UNIFIED_DIR/src/ethoscope" ]]; then
        cd "$NEW_UNIFIED_DIR/src/ethoscope"
        pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install ethoscope package"
    fi
    
    # Enable services
    log "Enabling services..."
    for service in ethoscope_backup ethoscope_node ethoscope_update_node ethoscope_video_backup; do
        if [[ -f "/usr/lib/systemd/system/${service}.service" ]]; then
            systemctl enable "${service}.service" || warn "Failed to enable ${service}.service"
        fi
    done
}

# Migrate device installation
migrate_device() {
    log "Migrating device installation..."
    
    # Move directory
    log "Moving $OLD_DEVICE_DIR to $NEW_UNIFIED_DIR..."
    mv "$OLD_DEVICE_DIR" "$NEW_UNIFIED_DIR"
    
    # Remove old service files
    log "Removing old service files..."
    for service in "${DEVICE_SERVICES[@]}"; do
        rm -f "/usr/lib/systemd/system/${service}.service"
        rm -f "/etc/systemd/system/${service}.service"
    done
    
    # Link new service files
    log "Linking new service files..."
    for service in "${DEVICE_SERVICES[@]}"; do
        if [[ -f "$NEW_UNIFIED_DIR/scripts/${service}.service" ]]; then
            ln -sf "$NEW_UNIFIED_DIR/scripts/${service}.service" "/usr/lib/systemd/system/"
            log "Linked ${service}.service"
        else
            warn "Service file not found: $NEW_UNIFIED_DIR/scripts/${service}.service"
        fi
    done
    
    # Install Python package
    log "Installing ethoscope Python package..."
    if [[ -d "$NEW_UNIFIED_DIR/src/ethoscope" ]]; then
        cd "$NEW_UNIFIED_DIR/src/ethoscope"
        pip install -e . --break-system-packages --no-build-isolation || warn "Failed to install ethoscope package"
    fi
    
    # Enable services
    log "Enabling services..."
    for service in ethoscope_device ethoscope_listener ethoscope_GPIO_listener ethoscope_update; do
        if [[ -f "/usr/lib/systemd/system/${service}.service" ]]; then
            systemctl enable "${service}.service" || warn "Failed to enable ${service}.service"
        fi
    done
}

# Reload systemd and start services
finalize_migration() {
    local install_type="$1"
    
    log "Reloading systemd daemon..."
    systemctl daemon-reload
    
    log "Starting services..."
    local services_to_start=()
    
    case "$install_type" in
        "node")
            services_to_start+=(ethoscope_node ethoscope_backup ethoscope_update_node ethoscope_video_backup)
            ;;
        "device")
            services_to_start+=(ethoscope_device ethoscope_listener ethoscope_GPIO_listener ethoscope_update)
            ;;
    esac
    
    for service in "${services_to_start[@]}"; do
        if [[ -f "/usr/lib/systemd/system/${service}.service" ]]; then
            log "Starting ${service}.service..."
            systemctl start "${service}.service" || warn "Failed to start ${service}.service"
        fi
    done
}

# Main migration function
perform_migration() {
    local auto_mode="$1"
    
    log "Starting ethoscope repository structure migration..."
    
    # Detect installation type
    local install_type
    install_type=$(detect_installation_type)
    
    case "$install_type" in
        "none")
            log "No ethoscope installation found. Nothing to migrate."
            exit 0
            ;;
        "node"|"device")
            log "Detected installation type: $install_type"
            ;;
        *)
            error "Unknown installation state: $install_type"
            exit 1
            ;;
    esac
    
    # Interactive confirmation unless in auto mode
    if [[ "$auto_mode" != "--auto" ]]; then
        echo
        warn "This will migrate your ethoscope installation to the new unified structure."
        warn "Make sure you have already pulled the latest dev branch changes."
        echo
        log "The script will:"
        echo "  1. Stop running services"
        echo "  2. Move directories to /opt/ethoscope"
        echo "  3. Update service file links"
        echo "  4. Install Python packages"
        echo "  5. Enable and start services"
        echo
        read -p "Do you want to continue? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Migration cancelled by user"
            exit 0
        fi
    fi
    
    # Perform migration steps
    stop_services "$install_type"
    
    case "$install_type" in
        "node")
            migrate_node
            ;;
        "device")
            migrate_device
            ;;
    esac
    
    finalize_migration "$install_type"
    
    success "Migration completed successfully!"
    echo
    log "New unified structure created at: $NEW_UNIFIED_DIR"
    echo
    success "Ethoscope migration to unified structure completed!"
}

# Print usage information
usage() {
    cat << EOF
Ethoscope Repository Structure Migration Script

This script migrates from the old separate directory structure to the new unified structure.
Run this AFTER pulling the latest dev branch changes.

Usage:
  sudo $0 [OPTIONS]

Options:
  --auto      Perform migration automatically without prompts
  --check     Show current installation state and exit
  --help      Show this help message

Examples:
  sudo $0                    # Interactive migration
  sudo $0 --auto            # Automatic migration
  sudo $0 --check           # Check current state

Prerequisites:
  1. Pull latest dev branch: git pull origin dev
  2. Run this script as root: sudo $0

The script will:
1. Move /opt/ethoscope-{device,node} to /opt/ethoscope
2. Update systemd service file links
3. Install Python packages in development mode
4. Enable and restart services
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
            perform_migration --auto
            ;;
        "")
            check_root
            perform_migration
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