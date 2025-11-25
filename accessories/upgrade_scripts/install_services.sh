#!/bin/bash

# Script to install ethoscope systemd services
# Usage: ./install_services.sh [--node|--ethoscope]

set -e

function show_usage() {
    echo "Usage: $0 [--node|--ethoscope]"
    echo "  --node      Install services for ethoscope node"
    echo "  --ethoscope Install services for ethoscope device"
    exit 1
}

function stop_and_disable_services() {
    local service_pattern="$1"
    echo "Stopping and disabling old ethoscope services matching pattern: $service_pattern"

    # Find all ethoscope services and stop/disable them
    local services=()

    # Collect services from both directories
    if [ -d "/usr/lib/systemd/system" ]; then
        while IFS= read -r -d '' service; do
            services+=("$(basename "$service")")
        done < <(find /usr/lib/systemd/system -name "$service_pattern" -type f -print0 2>/dev/null)
    fi

    if [ -d "/etc/systemd/system" ]; then
        while IFS= read -r -d '' service; do
            services+=("$(basename "$service")")
        done < <(find /etc/systemd/system -name "$service_pattern" -type f -print0 2>/dev/null)
    fi

    # Remove duplicates and process each service
    local unique_services=($(printf '%s\n' "${services[@]}" | sort -u))

    for service in "${unique_services[@]}"; do
        echo "Stopping and disabling $service"
        systemctl stop "$service" 2>/dev/null || true
        systemctl disable "$service" 2>/dev/null || true
    done
}

function remove_old_services() {
    local service_pattern="$1"
    echo "Removing old ethoscope services matching pattern: $service_pattern"

    # First stop and disable all services
    stop_and_disable_services "$service_pattern"

    # More explicit removal from both directories
    for dir in "/usr/lib/systemd/system" "/etc/systemd/system"; do
        if [ -d "$dir" ]; then
            echo "Cleaning $dir"
            # Use shell globbing which is more reliable than find for this case
            rm -f "$dir"/ethoscope_*.service 2>/dev/null || true
            rm -f "$dir"/ethoscope_*.timer 2>/dev/null || true
        fi
    done

    # Force daemon reload after cleanup
    systemctl daemon-reload
}

function link_services() {
    local -a services=("$@")

    for service in "${services[@]}"; do
        local source_file="/opt/ethoscope/services/$service"
        local target_file="/usr/lib/systemd/system/$service"

        if [ -f "$source_file" ]; then
            echo "Linking $service"
            ln -sf "$source_file" "$target_file"
        else
            echo "Warning: Service file $source_file not found"
        fi
    done
}

function reload_systemd() {
    echo "Reloading systemd daemon"
    systemctl daemon-reload
}

function enable_services() {
    local -a services=("$@")

    for service in "${services[@]}"; do
        echo "Enabling $service"
        systemctl enable "$service"
    done
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root"
    exit 1
fi

# Parse command line arguments
case "$1" in
    --node)
        echo "Installing node services"

        # Remove old ethoscope services
        remove_old_services "ethoscope_*"

        # Define node services
        NODE_SERVICES=(
            "ethoscope_backup.service"
            "ethoscope_backup_incremental.service"
            "ethoscope_backup_static.service"
            "ethoscope_backup_video.service"
            "ethoscope_backup_unified.service"
            "ethoscope_backup_mysql.service"
            "ethoscope_node.service"
            "ethoscope_update_node.service"
            "ethoscope_virtuascope.service"
            "ethoscope_sensor_virtual.service"
            "ethoscope_tunnel.service"
        )

        # Define node services to enable
        NODE_ENABLE_SERVICES=(
            "ethoscope_node"
            "ethoscope_backup_unified"
            # "ethoscope_backup_mysql"  # Not enabled by default (only needed if using MySQL result writer)
            "ethoscope_update_node"
            "ethoscope_sensor_virtual"
        )

        # Link new services
        link_services "${NODE_SERVICES[@]}"

        # Reload systemd and enable services
        reload_systemd
        enable_services "${NODE_ENABLE_SERVICES[@]}"
        ;;

    --ethoscope)
        echo "Installing ethoscope device services"

        # Remove old ethoscope services
        remove_old_services "ethoscope_*"

        # Define ethoscope services
        ETHOSCOPE_SERVICES=(
            "ethoscope_device.service"
            "ethoscope_listener.service"
            "ethoscope_GPIO_listener.service"
            "ethoscope_update.service"
        )

        # Define ethoscope services to enable
        ETHOSCOPE_ENABLE_SERVICES=(
            "ethoscope_listener"
            "ethoscope_device"
            "ethoscope_update"
            "ethoscope_GPIO_listener"
        )

        # Link new services
        link_services "${ETHOSCOPE_SERVICES[@]}"

        # Reload systemd and enable services
        reload_systemd
        enable_services "${ETHOSCOPE_ENABLE_SERVICES[@]}"
        ;;

    *)
        show_usage
        ;;
esac

echo "Service installation completed successfully"
