#!/bin/sh

if [ -z "${REPO_URL}" ]; then
    echo "REPO_URL environment variable is not set. Unable to initialize the git server."
    exit 1
fi

GIT_PROJECT=$(basename "$REPO_URL" .git)

if [ ! -d "${GIT_PROJECT}.git" ]; then
    echo "Cloning repository..."
    git clone --bare "${REPO_URL}" "${GIT_PROJECT}.git"
fi

cd "${GIT_PROJECT}.git"

# Update the repository every minute
while :; do
    echo "Updating repository..."
    git fetch --all
    sleep 60
done &

echo "Starting Git daemon..."

exec /usr/libexec/git-core/git-daemon --export-all --base-path=/srv/git --verbose --informative-errors --enable=receive-pack --listen=0.0.0.0 --port=9418 /srv/git
