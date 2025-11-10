#!/bin/bash

# update-node-cli.sh - Update ethoscope node from git repository
# Usage: ./update-node-cli.sh [--all]

set -e

# Check if --all flag is provided
ALL_FLAG=false
if [[ "$1" == "--all" ]]; then
    ALL_FLAG=true
fi

echo "Starting ethoscope node update..."

# 1. Find the source of /opt/ethoscope git repo
if [[ -d "/opt/ethoscope/.git" ]]; then
    # Regular git repo
    REPO_PATH="/opt/ethoscope"
    IS_BARE=false
    echo "Found regular git repository at $REPO_PATH"
elif [[ -d "/srv/git/ethoscope.git" ]]; then
    # Bare repository
    REPO_PATH="/srv/git/ethoscope.git"
    IS_BARE=true
    echo "Found bare git repository at $REPO_PATH"
else
    echo "Error: Could not find ethoscope git repository"
    echo "Checked: /opt/ethoscope/.git and /srv/git/ethoscope.git"
    exit 1
fi

# 2. If it's a bare repo, sync it with remote
if [[ "$IS_BARE" == "true" ]]; then
    echo "Syncing bare repository with remote..."
    cd "$REPO_PATH"
    sudo git fetch origin
    echo "Bare repository synced"
fi

# 3. Git pull from /opt/ethoscope
echo "Updating /opt/ethoscope..."
cd /opt/ethoscope
sudo git pull
echo "Git pull completed"

# 4. Restart ethoscope_node.service
echo "Restarting ethoscope_node.service..."
sudo systemctl restart ethoscope_node.service
echo "ethoscope_node.service restarted"

# 5. If --all flag is used, restart additional services
if [[ "$ALL_FLAG" == "true" ]]; then
    echo "Restarting additional services..."

    # Restart update server
    echo "Restarting ethoscope_update_server..."
    sudo systemctl restart ethoscope_update_server.service || echo "Warning: ethoscope_update_server.service not found or failed to restart"

    # Find and restart active backup service
    echo "Finding active backup service..."
    if systemctl is-active --quiet ethoscope_backup_unified.service; then
        echo "Restarting ethoscope_backup_unified.service..."
        sudo systemctl restart ethoscope_backup_unified.service

    elif systemctl is-active --quiet ethoscope_backup_node.service; then
        echo "Restarting ethoscope_update_node.service..."
        sudo systemctl restart ethoscope_update_node.service

    elif systemctl is-active --quiet ethoscope_backup_mysql.service; then
        echo "Restarting ethoscope_backup_mysql.service..."
        sudo systemctl restart ethoscope_backup_mysql.service

    elif systemctl is-active --quiet ethoscope_backup_video.service; then
        echo "Restarting ethoscope_backup_video.service..."
        sudo systemctl restart ethoscope_backup_video.service

    elif systemctl is-active --quiet ethoscope_backup_sqlite.service; then
        echo "Restarting ethoscope_backup_sqlite.service..."
        sudo systemctl restart ethoscope_backup_sqlite.service

    else
        echo "Warning: No active backup service found"
    fi

    echo "All services restarted"
fi

echo "Ethoscope node update completed successfully!"
