#!/bin/bash

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

# Constants
readonly ETHOSCOPE_PATH="/opt/ethoscope"
readonly GITHUB_REPO="https://github.com/gilestrolab/ethoscope.git"
readonly LOCAL_REPO="git://node/ethoscope.git"
readonly MACHINE_NAME="ETHOSCOPE_000"

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check if the script is run as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        echo "Usage: sudo $0 [--update|--fresh]"
        exit 1
    fi
}

# Function to validate git repository
validate_git_repo() {
    local repo_path="$1"
    if [[ ! -d "$repo_path/.git" ]]; then
        log_error "Invalid git repository at $repo_path"
        return 1
    fi
}

# Function to perform update
update_repository() {
    log_info "Updating repository and changing origin..."
    
    if [[ ! -d "$ETHOSCOPE_PATH" ]]; then
        log_error "Ethoscope directory not found at $ETHOSCOPE_PATH"
        log_info "Use --fresh flag to clone the repository"
        exit 1
    fi
    
    cd "$ETHOSCOPE_PATH" || {
        log_error "Failed to change directory to $ETHOSCOPE_PATH"
        exit 1
    }
    
    validate_git_repo "$ETHOSCOPE_PATH"
    
    # Stash any local changes to avoid conflicts
    if git status --porcelain | grep -q .; then
        log_warn "Local changes detected. Stashing them..."
        git stash
    fi
    
    git remote set-url origin "$GITHUB_REPO"
    git fetch origin
    git pull origin dev
    git checkout dev
    git remote set-url origin "$LOCAL_REPO"
    
    log_info "Repository updated successfully"
}

# Function to remove and reinstall repository
remove_and_reinstall_repository() {
    log_info "Performing fresh installation..."
    
    # Remove existing ethoscope directories
    rm -rf /opt/ethoscope*
    
    # Clone repository
    if ! git clone "$GITHUB_REPO" "$ETHOSCOPE_PATH"; then
        log_error "Failed to clone repository"
        exit 1
    fi
    
    cd "$ETHOSCOPE_PATH" || {
        log_error "Failed to change directory to $ETHOSCOPE_PATH"
        exit 1
    }
    
    git checkout dev
    git remote set-url origin "$LOCAL_REPO"
    
    # Install ethoscope package
    if [[ -d "$ETHOSCOPE_PATH/src/ethoscope" ]]; then
        cd "$ETHOSCOPE_PATH/src/ethoscope"
        if command -v pip &> /dev/null; then
            pip install -e . --break-system-packages
        else
            log_error "pip not found. Cannot install ethoscope package"
            exit 1
        fi
    else
        log_warn "Ethoscope source directory not found. Skipping pip install"
    fi
    
    # Enable systemd services
    for service in ethoscope_device ethoscope_listener; do
        if systemctl list-unit-files | grep -q "^$service.service"; then
            systemctl enable "$service"
            log_info "Enabled $service service"
        else
            log_warn "$service.service not found. Skipping enable"
        fi
    done
    
    log_info "Fresh installation completed successfully"
}

# Function to set system date
set_system_date() {
    log_info "Setting correct date from internet..."
    
    if command -v wget &> /dev/null; then
        local date_string
        date_string=$(wget --method=HEAD -qSO- --max-redirect=0 --timeout=10 google.com 2>&1 | grep "Date:" | cut -d' ' -f5-10)
        
        if [[ -n "$date_string" ]]; then
            date -s "$date_string"
            log_info "System date updated"
        else
            log_warn "Failed to retrieve date from internet"
        fi
    else
        log_warn "wget not found. Cannot set system date"
    fi
}

# Function to configure machine identity
configure_machine_identity() {
    log_info "Configuring machine identity..."
    
    echo "$MACHINE_NAME" > /etc/machine-name
    echo "$MACHINE_NAME" > /etc/hostname
    
    log_info "Machine name set to $MACHINE_NAME"
}

# Function to set timezone
set_timezone() {
    log_info "Setting timezone to UTC..."
    
    if command -v timedatectl &> /dev/null; then
        timedatectl set-timezone UTC
    else
        log_warn "timedatectl not found. Cannot set timezone"
    fi
}

# Function to create network configuration
create_network_config() {
    log_info "Creating network configuration files..."
    
    # Wired network configuration
    cat > /etc/systemd/network/20-wired.network << 'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes

[DHCPv4]
RouteMetric=10
EOF

    # Wireless network configuration
    cat > /etc/systemd/network/25-wireless.network << 'EOF'
[Match]
Name=wlan0

[Network]
DHCP=yes

[DHCPv4]
RouteMetric=20
EOF

    log_info "Network configuration files created"
}

# Function to clean package cache
clean_package_cache() {
    log_info "Cleaning package cache..."
    
    if command -v pacman &> /dev/null; then
        log_info "Cleaning Pacman cache..."
        pacman -Scc --noconfirm
    elif command -v apt-get &> /dev/null; then
        log_info "Cleaning APT cache..."
        apt-get clean
    else
        log_warn "No recognized package manager found. Skipping cache clean"
    fi
}

# Function to show usage information
show_usage() {
    cat << EOF
Usage: $0 [OPTION]

Options:
    --update    Update existing repository only
    --fresh     Remove and reinstall repository completely
    --help      Show this help message

If no option is provided, the script will update the repository and 
perform full system configuration.
EOF
}

# Main execution logic
main() {
    check_root
    
    case "${1:-}" in
        --update)
            update_repository
            exit 0
            ;;
        --fresh)
            remove_and_reinstall_repository
            exit 0
            ;;
        --help)
            show_usage
            exit 0
            ;;
        "")
            # Default behavior: full setup
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
    
    # Full setup (when no flags provided)
    log_info "Starting full ethoscope setup..."
    
    update_repository
    set_system_date
    configure_machine_identity
    set_timezone
    create_network_config
    clean_package_cache
    
    log_info "Setup completed successfully!"
    log_warn "System reboot recommended"
}

# Run main function with all arguments
main "$@"